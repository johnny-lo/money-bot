"""line_messages／line_listener_state 的唯一 DB 存取層。"""
import json
from datetime import datetime

from models import LineListenerState, LineMessage

from .clock import now_taipei
from .types import NEEDS_CODEX, OK, InboxMessage, ListenerState


def exists(db, message_id: str) -> bool:
    return db.query(LineMessage.id).filter(LineMessage.message_id == message_id).first() is not None


def save_message(db, m: InboxMessage, status: str, error: str | None = None) -> bool:
    """新的才寫；已存在就回 False、不覆蓋（補讀會重複看到同一則）。"""
    if db.query(LineMessage).filter(LineMessage.message_id == m.message_id).first() is not None:
        return False
    db.add(LineMessage(message_id=m.message_id, source=m.source, sent_at=m.sent_at, alt_text=m.alt_text,
                       content_type=m.content_type, texts=json.dumps(m.texts, ensure_ascii=False),
                       kind=m.kind, status=status, error=error))
    db.commit()
    return True


def set_status(db, message_id: str, status: str, error: str | None = None) -> None:
    row = db.query(LineMessage).filter(LineMessage.message_id == message_id).first()
    if row is not None:
        row.status, row.error = status, error
        db.commit()


def pending_codex(db, limit: int) -> list[InboxMessage]:
    rows = (db.query(LineMessage).filter(LineMessage.status == NEEDS_CODEX)
            .order_by(LineMessage.sent_at, LineMessage.id).limit(limit).all())
    return [InboxMessage(r.message_id, r.source, r.sent_at, r.alt_text, r.content_type, json.loads(r.texts), r.kind)
            for r in rows]


def set_state(db, state: str, error: str | None = None, now: datetime | None = None) -> None:
    """心跳只在狀態正常時前進：卡在錯誤或被踢時 heartbeat_at 停住，watchdog 才看得出停擺。正常時清掉已告警。"""
    row = db.get(LineListenerState, 1)
    if row is None:
        row = LineListenerState(id=1, state=state, heartbeat_at=None, last_error=None, alerted=None)
        db.add(row)
    row.state, row.last_error = state, error
    if state == OK:
        row.heartbeat_at = now or now_taipei()
        row.alerted = None
    db.commit()


def listener_state(db) -> ListenerState | None:
    row = db.get(LineListenerState, 1)
    if row is None:
        return None
    return ListenerState(row.state, row.heartbeat_at, row.last_error, row.alerted)


def mark_alerted(db, kind: str) -> None:
    row = db.get(LineListenerState, 1)
    if row is not None:
        row.alerted = kind
        db.commit()


def spend_count_since(db, since: datetime) -> int:
    return (db.query(LineMessage).filter(LineMessage.kind == "spend", LineMessage.sent_at >= since).count())
