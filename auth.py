import secrets
from datetime import datetime, timedelta
from fastapi import Query, Header, HTTPException

from database import SessionLocal
from models import DeviceToken

# { token: {"user_id": str, "expires_at": datetime} }
_token_store: dict = {}

TOKEN_TTL_MINUTES = 30


def require_token(token: str = Query(None),
                  x_device_token: str = Header(None)):
    """FastAPI dependency：驗證 token，失敗回傳 401。

    兩種憑證擇一即可：
    - token（query）：30 分鐘短效，從 Discord/LINE 取得連結時帶上
    - X-Device-Token（header）：PWA 長效裝置 token（用短效 token 換發，存 DB）
    """
    if token and validate_report_token(token):
        return
    if x_device_token and validate_device_token(x_device_token):
        return
    raise HTTPException(status_code=401, detail="無效或過期的連結，請在 LINE Bot 傳送「報表」重新取得連結。")


def generate_report_token(user_id: str, *, can_mint_device: bool = True) -> str:
    """產生一次性報表 token，有效期 30 分鐘。

    `can_mint_device` 決定這顆 token 能不能再去換長效裝置 token（routes/device.py）。
    LINE/Discord 發出去的連結是「剛從對話拿到的邀請函」→ True。
    PWA 拿裝置 token 鑄出來、只為了開報表頁的那顆 → 必須 False：
    否則 device → short → device 成環，「洩漏的裝置 token 無法自我繁殖」就不成立了。
    """
    _cleanup_expired()
    token = secrets.token_urlsafe(32)
    _token_store[token] = {
        "user_id": user_id,
        "expires_at": datetime.now() + timedelta(minutes=TOKEN_TTL_MINUTES),
        "can_mint_device": can_mint_device,
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


def report_token_can_mint_device(token: str) -> bool:
    """這顆短效 token 能不能換長效裝置 token。無效/過期/沒旗標一律 False。

    預設關閉（`.get(..., False)`）——新的鑄幣路徑忘了標記時，後果應該是「換不到」
    而不是「默默放行」。
    """
    if not token or not validate_report_token(token):
        return False
    return bool(_token_store[token].get("can_mint_device", False))


def _cleanup_expired():
    """清除過期 token"""
    now = datetime.now()
    expired = [t for t, v in _token_store.items() if now > v["expires_at"]]
    for t in expired:
        del _token_store[t]


# ─── PWA 裝置 token（長效、存 DB）─────────────────────────────

def create_device_token(label: str = "") -> str:
    """換發一顆長效裝置 token。呼叫端必須先驗過短效 token（見 routes/device.py）。"""
    token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        db.add(DeviceToken(token=token, label=label or None))
        db.commit()
        return token
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def validate_device_token(token: str) -> bool:
    """查 DB 驗證裝置 token，命中順手記 last_used_at（看哪台裝置還活著）。"""
    if not token:
        return False
    db = SessionLocal()
    try:
        rec = db.query(DeviceToken).filter(DeviceToken.token == token).first()
        if rec is None:
            return False
        rec.last_used_at = datetime.now()
        db.commit()
        return True
    finally:
        db.close()


def revoke_device_token(token: str) -> bool:
    """撤銷一顆裝置 token（裝置遺失/換手機時用）。刪到回 True。"""
    db = SessionLocal()
    try:
        rec = db.query(DeviceToken).filter(DeviceToken.token == token).first()
        if rec is None:
            return False
        db.delete(rec)
        db.commit()
        return True
    finally:
        db.close()
