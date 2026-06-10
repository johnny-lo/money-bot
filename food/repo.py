"""FoodPlace 的 DB 存取（沿用 SessionLocal 慣例）。"""
from database import SessionLocal
from models import FoodPlace


def to_dict(rec: FoodPlace) -> dict:
    """ORM → dict，供 embed / recommend 純函式使用。"""
    return {
        "id": rec.id,
        "name": rec.name,
        "address": rec.address,
        "lat": rec.lat,
        "lng": rec.lng,
        "place_id": rec.place_id,
        "country": rec.country,
        "city": rec.city,
        "district": rec.district,
        "cuisine_type": rec.cuisine_type,
        "recommended_items": rec.recommended_items,
        "caution_summary": rec.caution_summary,
        "status": rec.status,
        "my_rating": rec.my_rating,
        "my_note": rec.my_note,
        "source_url": rec.source_url,
        "created_at": rec.created_at.isoformat() if rec.created_at else "",
    }


def upsert_place(place: dict, *, recommended_items=None, cuisine_type=None,
                 source_url=None) -> tuple[dict, bool]:
    """以 place_id 去重。回 (dict, created)；created=False 表示更新既有店。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.place_id == place["place_id"]).first()
        created = rec is None
        if rec is None:
            rec = FoodPlace(place_id=place["place_id"], status="想去")
            db.add(rec)
        rec.name = place["name"]
        rec.address = place.get("address")
        rec.lat = place.get("lat")
        rec.lng = place.get("lng")
        rec.country = place.get("country")
        rec.city = place.get("city")
        rec.district = place.get("district")
        if recommended_items:
            rec.recommended_items = recommended_items
        if cuisine_type:
            rec.cuisine_type = cuisine_type
        if source_url:
            rec.source_url = source_url
        db.commit()
        db.refresh(rec)
        return to_dict(rec), created
    finally:
        db.close()


def list_places(status: str | None = None) -> list[dict]:
    """列出店家（可選狀態），新到舊。"""
    db = SessionLocal()
    try:
        q = db.query(FoodPlace)
        if status:
            q = q.filter(FoodPlace.status == status)
        rows = q.order_by(FoodPlace.created_at.desc()).all()
        return [to_dict(r) for r in rows]
    finally:
        db.close()


def set_visited(food_id: int, rating: int | None = None,
                note: str | None = None) -> dict | None:
    """把某筆標成『去過』，可帶評分/心得。查無回 None。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is None:
            return None
        rec.status = "去過"
        if rating is not None:
            rec.my_rating = rating
        if note:
            rec.my_note = note
        db.commit()
        db.refresh(rec)
        return to_dict(rec)
    finally:
        db.close()


def set_message_id(food_id: int, message_id) -> None:
    """記下這筆 FoodPlace 對應的 Discord 卡片訊息 ID（給 ✅ 反應回查用）。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is not None:
            rec.discord_message_id = str(message_id)
            db.commit()
    finally:
        db.close()


def update_caution(food_id: int, caution: str) -> None:
    """事後加值雷點摘要。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is not None:
            rec.caution_summary = caution
            db.commit()
    finally:
        db.close()


def update_recommended(food_id: int, text: str) -> None:
    """事後補上推薦菜（Google 評論萃取）。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is not None:
            rec.recommended_items = text
            db.commit()
    finally:
        db.close()


def set_visited_by_message_id(message_id) -> dict | None:
    """從 Discord 卡片訊息 ID 反查 FoodPlace，標為去過。查無回 None。"""
    db = SessionLocal()
    try:
        rec = (
            db.query(FoodPlace)
            .filter(FoodPlace.discord_message_id == str(message_id))
            .first()
        )
        if rec is None:
            return None
        rec.status = "去過"
        db.commit()
        db.refresh(rec)
        return to_dict(rec)
    finally:
        db.close()


def delete_place(food_id: int) -> bool:
    """依編號(FoodPlace.id)刪除一家店。刪到回 True、查無回 False。

    回 bool（與 set_visited 的 dict-or-None 不同）：刪除只需成功/失敗布林（spec §7）。
    """
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is None:
            return False
        db.delete(rec)
        db.commit()
    finally:
        db.close()
    # DB 刪成功才清照片檔案（DB 列由 FK CASCADE 自動清）
    from food import photos
    photos.delete_files_for_place(food_id)
    return True
