"""Recipe 的 DB 存取（沿用 SessionLocal 慣例）。"""
import random

from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import Recipe


def to_dict(rec: Recipe) -> dict:
    """ORM → dict，供 embed 使用。"""
    return {
        "id": rec.id,
        "name": rec.name,
        "url": rec.url,
        "platform": rec.platform,
        "discord_message_id": rec.discord_message_id,
        "created_at": rec.created_at.isoformat() if rec.created_at else "",
    }


def _get_by_url(db, url: str):
    return db.query(Recipe).filter(Recipe.url == url).first()


def add_recipe(name: str, url: str, platform: str | None = None) -> tuple[dict, bool]:
    """以 url 去重。回 (dict, created)。

    SELECT→INSERT；併發下兩個 thread 可能都 SELECT 落空、都 INSERT，
    後者 commit 撞 UNIQUE(url) → rollback → 重新依 url SELECT → 當『已收錄過』回。
    """
    db = SessionLocal()
    try:
        existing = _get_by_url(db, url)
        if existing is not None:
            return to_dict(existing), False
        rec = Recipe(name=name, url=url, platform=platform)
        db.add(rec)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            dup = _get_by_url(db, url)
            if dup is not None:
                return to_dict(dup), False
            raise
        db.refresh(rec)
        return to_dict(rec), True
    finally:
        db.close()


def list_recipes() -> list[dict]:
    """列出所有食譜，新到舊。"""
    db = SessionLocal()
    try:
        rows = db.query(Recipe).order_by(Recipe.created_at.desc()).all()
        return [to_dict(r) for r in rows]
    finally:
        db.close()


def pick_random() -> dict | None:
    """隨機抽一道（載入後 random.choice，不用 SQL random()）。空庫回 None。"""
    rows = list_recipes()
    return random.choice(rows) if rows else None


def delete_recipe(recipe_id: int) -> bool:
    """刪除一筆。True=刪了，False=查無。"""
    db = SessionLocal()
    try:
        rec = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if rec is None:
            return False
        db.delete(rec)
        db.commit()
        return True
    finally:
        db.close()


def set_message_id(recipe_id: int, message_id) -> None:
    """記下這筆 Recipe 對應的 Discord 卡片訊息 ID（給 reply 改名回查用）。"""
    db = SessionLocal()
    try:
        rec = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if rec is not None:
            rec.discord_message_id = str(message_id)
            db.commit()
    finally:
        db.close()


def rename(recipe_id: int, new_name: str) -> dict | None:
    """改菜名。查無回 None。"""
    db = SessionLocal()
    try:
        rec = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if rec is None:
            return None
        rec.name = (new_name or "").strip()
        db.commit()
        db.refresh(rec)
        return to_dict(rec)
    finally:
        db.close()


def get_by_message_id(message_id) -> dict | None:
    """從 Discord 卡片訊息 ID 反查 Recipe（純 getter，不改狀態）。查無回 None。"""
    db = SessionLocal()
    try:
        rec = (
            db.query(Recipe)
            .filter(Recipe.discord_message_id == str(message_id))
            .first()
        )
        return to_dict(rec) if rec is not None else None
    finally:
        db.close()
