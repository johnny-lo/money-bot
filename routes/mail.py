"""信件名單 JSON API（PWA 📬 分頁用）。唯讀：只讀 mail_* 三張表，不碰 Gmail。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_token
from mailrules import views

router = APIRouter()

_KEYS = {k for k, _ in views.LAYERS}


def _today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


@router.get("/api/mail/overview", dependencies=[Depends(require_token)])
def api_mail_overview():
    """每一層現有幾筆（照 views.LAYERS 順序）。"""
    return {"layers": views.overview(None, _today())}


@router.get("/api/mail/layers/{key}", dependencies=[Depends(require_token)])
def api_mail_layer(key: str, q: str = "", offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500)):
    """某一層的名單（新到舊；q 不分大小寫搜尋；offset/limit 分頁）。"""
    if key not in _KEYS:
        raise HTTPException(status_code=404, detail=f"沒有這一層：{key}")
    return views.layer(None, key, _today(), q=q, offset=offset, limit=limit)
