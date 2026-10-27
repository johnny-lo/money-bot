from models import LineListenerState, LineMessage
from lineinbox import config


def test_line_messages_欄位():
    cols = set(LineMessage.__table__.columns.keys())
    assert cols == {"id", "message_id", "source", "sent_at", "alt_text", "content_type", "texts", "kind",
                    "status", "error", "created_at", "updated_at"}
    assert LineMessage.__table__.columns["message_id"].unique


def test_line_listener_state_欄位():
    cols = set(LineListenerState.__table__.columns.keys())
    assert cols == {"id", "state", "heartbeat_at", "last_error", "alerted", "updated_at"}


def test_config():
    assert config.WATCHED == {"中國信託": "ctbc"}
    assert config.CHARGE_ID_PREFIX == "line:"
    assert config.SESSION_PATH == "/data/tokens.json"
    assert config.CODEX_FALLBACK_MODEL == "gpt-5.6-sol"
    assert (config.STALE_MIN, config.BACKOFF_START, config.BACKOFF_MAX) == (60, 5, 600)
