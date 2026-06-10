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


def backfill_all() -> None:
    """補強所有有 place_id 的店（一次性）。印進度。"""
    db = SessionLocal()
    try:
        rows = [(p.id, p.place_id, p.name, p.recommended_items)
                for p in db.query(FoodPlace).filter(FoodPlace.place_id.isnot(None)).all()]
    finally:
        db.close()

    total = len(rows)
    print(f"backfill {total} 家…", flush=True)
    n_reco = n_photo = 0
    for i, (fid, pid, name, cur) in enumerate(rows, 1):
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
    print(f"done. 補了推薦菜 {n_reco} 家、照片 {n_photo} 家。", flush=True)
