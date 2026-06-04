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
