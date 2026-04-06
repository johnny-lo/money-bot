import secrets
from datetime import datetime, timedelta
from fastapi import Query, HTTPException

# { token: {"user_id": str, "expires_at": datetime} }
_token_store: dict = {}

TOKEN_TTL_MINUTES = 30


def require_token(token: str = Query(None)):
    """FastAPI dependency：驗證 token，失敗回傳 401"""
    if not token or not validate_report_token(token):
        raise HTTPException(status_code=401, detail="無效或過期的連結，請在 LINE Bot 傳送「報表」重新取得連結。")


def generate_report_token(user_id: str) -> str:
    """產生一次性報表 token，有效期 30 分鐘"""
    _cleanup_expired()
    token = secrets.token_urlsafe(32)
    _token_store[token] = {
        "user_id": user_id,
        "expires_at": datetime.now() + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return token


def validate_report_token(token: str) -> str | None:
    """驗證 token，回傳 user_id；無效或過期則回傳 None"""
    entry = _token_store.get(token)
    if not entry:
        return None
    if datetime.now() > entry["expires_at"]:
        del _token_store[token]
        return None
    return entry["user_id"]


def _cleanup_expired():
    """清除過期 token"""
    now = datetime.now()
    expired = [t for t, v in _token_store.items() if now > v["expires_at"]]
    for t in expired:
        del _token_store[t]
