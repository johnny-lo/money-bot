"""HistoryVideo + VideoTag 的 DB 存取（沿用 recipe/repo.py 的 SessionLocal 慣例）。

標籤去正規化：VideoTag 直接存標籤字串。查某標籤=WHERE tag=?；全部標籤=DISTINCT tag。
"""
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import HistoryVideo, VideoTag
from video.extract import youtube_thumbnail


def to_dict(rec: HistoryVideo, tags: list[str] | None = None) -> dict:
    """ORM → dict。thumbnail 由 url 算；tags 由呼叫端附（預設空）。"""
    return {
        "id": rec.id,
        "title": rec.title,
        "url": rec.url,
        "topic": rec.topic,
        "channel": rec.channel,
        "platform": rec.platform,
        "thumbnail": youtube_thumbnail(rec.url or ""),
        "tags": tags or [],
        "discord_message_id": rec.discord_message_id,
        "created_at": rec.created_at.isoformat() if rec.created_at else "",
    }


def _get_by_url(db, url: str):
    return db.query(HistoryVideo).filter(HistoryVideo.url == url).first()


def tags_for(video_id: int) -> list[str]:
    """某影片的標籤（建立順序）。"""
    db = SessionLocal()
    try:
        rows = (db.query(VideoTag)
                .filter(VideoTag.video_id == video_id)
                .order_by(VideoTag.id.asc()).all())
        return [r.tag for r in rows]
    finally:
        db.close()


def tags_by_video() -> dict[int, list[str]]:
    """一次撈全部標籤，分組成 {video_id: [tag]}（給 list_videos 附掛，仿 photos_by_place）。"""
    db = SessionLocal()
    try:
        rows = db.query(VideoTag).order_by(VideoTag.id.asc()).all()
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(r.video_id, []).append(r.tag)
        return out
    finally:
        db.close()


def add_video(title: str, url: str, topic: str | None = None,
              channel: str | None = None, platform: str | None = None) -> tuple[dict, bool]:
    """以 url 去重。回 (dict, created)。併發撞 UNIQUE(url) → rollback → 當『已收錄』回。"""
    db = SessionLocal()
    try:
        existing = _get_by_url(db, url)
        if existing is not None:
            return to_dict(existing), False
        rec = HistoryVideo(title=title, url=url, topic=topic,
                           channel=channel, platform=platform)
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


def list_videos(topic: str | None = None) -> list[dict]:
    """列出影片（新到舊），每筆附 tags。topic 給值則只回該書架。"""
    tags_map = tags_by_video()
    db = SessionLocal()
    try:
        q = db.query(HistoryVideo)
        if topic:
            q = q.filter(HistoryVideo.topic == topic)
        rows = q.order_by(HistoryVideo.created_at.desc()).all()
        return [to_dict(r, tags=tags_map.get(r.id, [])) for r in rows]
    finally:
        db.close()


def _get(db, video_id: int):
    return db.query(HistoryVideo).filter(HistoryVideo.id == video_id).first()


def get(video_id: int) -> dict | None:
    """單筆（含 tags）。查無回 None。"""
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return None
        out = to_dict(rec)
    finally:
        db.close()
    out["tags"] = tags_for(video_id)
    return out


def rename(video_id: int, title: str) -> dict | None:
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return None
        rec.title = (title or "").strip()
        db.commit()
    finally:
        db.close()
    return get(video_id)


def set_topic(video_id: int, topic: str) -> dict | None:
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return None
        rec.topic = (topic or "").strip() or None
        db.commit()
    finally:
        db.close()
    return get(video_id)


def add_tag(video_id: int, tag: str) -> bool:
    """加一個標籤（冪等：同 video 同 tag 已存在則略過）。video 不存在回 False。"""
    tag = (tag or "").strip()
    if not tag:
        return False
    db = SessionLocal()
    try:
        if _get(db, video_id) is None:
            return False
        dup = (db.query(VideoTag)
               .filter(VideoTag.video_id == video_id, VideoTag.tag == tag).first())
        if dup is not None:
            return True
        db.add(VideoTag(video_id=video_id, tag=tag))
        db.commit()
        return True
    finally:
        db.close()


def remove_tag(video_id: int, tag: str) -> bool:
    """刪一個標籤。True=刪了，False=查無。"""
    tag = (tag or "").strip()
    db = SessionLocal()
    try:
        row = (db.query(VideoTag)
               .filter(VideoTag.video_id == video_id, VideoTag.tag == tag).first())
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


def delete_video(video_id: int) -> bool:
    """刪影片（FK CASCADE 連帶刪 video_tags）。True=刪了，False=查無。"""
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return False
        db.delete(rec)
        db.commit()
        return True
    finally:
        db.close()


def set_message_id(video_id: int, message_id) -> None:
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is not None:
            rec.discord_message_id = str(message_id)
            db.commit()
    finally:
        db.close()


def get_by_message_id(message_id) -> dict | None:
    """從卡片訊息 ID 反查影片（含 tags）。查無回 None。"""
    db = SessionLocal()
    try:
        rec = (db.query(HistoryVideo)
               .filter(HistoryVideo.discord_message_id == str(message_id)).first())
        vid = rec.id if rec is not None else None
    finally:
        db.close()
    return get(vid) if vid is not None else None
