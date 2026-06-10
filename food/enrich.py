"""店家自動補強:用 Google Places 評論+照片,填推薦菜 + 抓一張 Google 照片。

兩個入口都呼叫 enrich_place:
- 新增店家後可順手補強(之後接)
- 一次性 backfill_all() 補既有的店(透過 docker exec 跑)

idempotent:推薦菜已有就不覆蓋、已有 google 照片就不再抓 → 可安全重跑補漏。
"""
from database import SessionLocal
from models import FoodPlace, FoodPhoto
from food.places import recommended_for_place_id, fetch_place_photo
from food.photos import add_photo
from food import repo


def _has_google_photo(food_id: int) -> bool:
    db = SessionLocal()
    try:
        return db.query(FoodPhoto).filter(
            FoodPhoto.food_place_id == food_id, FoodPhoto.source == "google"
        ).first() is not None
    finally:
        db.close()


def enrich_place(food_id: int, place_id: str, cur_recommended: str | None = None) -> dict:
    """補一家店:推薦菜(空才補) + Google 照片(沒有才抓)。回 {recommended, photo}。"""
    out = {"recommended": "", "photo": False}
    if not place_id:
        return out

    if not (cur_recommended and cur_recommended.strip()):
        dishes = recommended_for_place_id(place_id)
        if dishes:
            repo.update_recommended(food_id, dishes)
            out["recommended"] = dishes

    if not _has_google_photo(food_id):
        photo = fetch_place_photo(place_id)
        if photo:
            add_photo(food_id, photo[0], photo[1], source="google")
            out["photo"] = True
    return out


def _all_rows_with_place_id() -> list[tuple]:
    db = SessionLocal()
    try:
        return [(p.id, p.place_id, p.name, p.recommended_items)
                for p in db.query(FoodPlace).filter(FoodPlace.place_id.isnot(None)).all()]
    finally:
        db.close()


def backfill_all(max_api_calls: int = 200) -> None:
    """補強所有有 place_id 的店（一次性）。印進度。

    max_api_calls：本次允許的 Google API 呼叫上限（Places API New 按次計費）。
    超過就停並回報剩幾家——enrich_place 是 idempotent，改天再跑會從沒補到的接續。
    """
    import traceback
    from food import places

    rows = _all_rows_with_place_id()
    total = len(rows)
    print(f"backfill {total} 家…（API 預算 {max_api_calls} 次）", flush=True)
    n_reco = n_photo = 0
    start = places.api_call_count()
    for i, (fid, pid, name, cur) in enumerate(rows, 1):
        if places.api_call_count() - start >= max_api_calls:
            print(f"⛔ 已達 API 預算 {max_api_calls} 次，剩 {total - i + 1} 家未跑（重跑會自動接續）", flush=True)
            break
        try:
            r = enrich_place(fid, pid, cur)
            if r["recommended"]:
                n_reco += 1
            if r["photo"]:
                n_photo += 1
            print(f"[{i}/{total}] {name} "
                  f"reco={'✓' if r['recommended'] else '-'} "
                  f"photo={'✓' if r['photo'] else '-'}", flush=True)
        except Exception as e:
            print(f"[{i}/{total}] {name} ERROR {e}", flush=True)
            traceback.print_exc()
    print(f"done. 補了推薦菜 {n_reco} 家、照片 {n_photo} 家，"
          f"用了 {places.api_call_count() - start} 次 API。", flush=True)
