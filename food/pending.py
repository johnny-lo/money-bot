"""需補件 in-memory 暫存（無 TTL；bot 重啟丟失可接受）。"""
import time

_pending: dict[str, dict] = {}


def remember(bot_message_id, *, original_message_id, raw_text: str = "",
             source_url: str | None = None, attachment_url: str | None = None,
             missing_reason: str = "") -> None:
    """記下一張需補件卡片的上下文。"""
    key = str(bot_message_id)
    _pending[key] = {
        "bot_message_id": key,
        "original_message_id": str(original_message_id),
        "raw_text": raw_text,
        "source_url": source_url,
        "attachment_url": attachment_url,
        "missing_reason": missing_reason,
        "created_at": time.time(),
    }


def get(bot_message_id) -> dict | None:
    return _pending.get(str(bot_message_id))


def consume(bot_message_id) -> dict | None:
    """取出並移除一筆 pending（無就回 None）。"""
    return _pending.pop(str(bot_message_id), None)


def clear() -> None:
    """測試用：清空全部。"""
    _pending.clear()
