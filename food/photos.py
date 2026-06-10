"""店家照片庫：檔案存本機 media/，DB(food_photos) 只記相對路徑。

bot 路與 app 路最後都呼叫 add_photo() → 同一個存檔位置。
通則:二進位檔案存檔案系統,資料庫只存「指向它的路徑」,別把圖塞進 DB。
"""
import os
import uuid

from database import SessionLocal
from models import FoodPhoto

MEDIA_ROOT = "media"
_ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif", "heic"}


def _url(rel_path: str) -> str:
    """相對路徑 → 對外網址（FastAPI 把 media/ 掛在 /media）。"""
    return "/media/" + rel_path.replace("\\", "/")


def add_photo(food_place_id: int, data: bytes, ext: str = "jpg", source: str = "app") -> dict:
    """存一張照片:寫檔到 media/food/<id>/<uuid>.<ext> + DB 記一筆。回 {id, url, source}。"""
    ext = (ext or "jpg").lower().lstrip(".")
    if ext not in _ALLOWED_EXT:
        ext = "jpg"
    rel_dir = os.path.join("food", str(food_place_id))
    os.makedirs(os.path.join(MEDIA_ROOT, rel_dir), exist_ok=True)
    rel_path = os.path.join(rel_dir, f"{uuid.uuid4().hex}.{ext}")
    with open(os.path.join(MEDIA_ROOT, rel_path), "wb") as f:
        f.write(data)

    db = SessionLocal()
    try:
        rec = FoodPhoto(food_place_id=food_place_id, path=rel_path, source=source)
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return {"id": rec.id, "url": _url(rec.path), "source": rec.source}
    finally:
        db.close()


def list_photos(food_place_id: int) -> list[dict]:
    """某家店的所有照片(舊到新)。"""
    db = SessionLocal()
    try:
        rows = (db.query(FoodPhoto)
                .filter(FoodPhoto.food_place_id == food_place_id)
                .order_by(FoodPhoto.created_at).all())
        return [{"id": r.id, "url": _url(r.path), "source": r.source} for r in rows]
    finally:
        db.close()


def photos_by_place() -> dict:
    """一次撈全部,分組成 {place_id: [url,...]}（給清單 API 批次帶上,避免 N+1）。"""
    db = SessionLocal()
    try:
        rows = db.query(FoodPhoto).order_by(FoodPhoto.created_at).all()
        out: dict = {}
        for r in rows:
            out.setdefault(r.food_place_id, []).append(_url(r.path))
        return out
    finally:
        db.close()


def delete_photo(photo_id: int) -> bool:
    """刪一張(DB + 檔案)。查無回 False。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPhoto).filter(FoodPhoto.id == photo_id).first()
        if rec is None:
            return False
        try:
            os.remove(os.path.join(MEDIA_ROOT, rec.path))
        except OSError:
            pass
        db.delete(rec)
        db.commit()
        return True
    finally:
        db.close()
