"""PWA 裝置 token 換發。

流程：手機從 Discord 點 /m/?token=<短效> 開啟 PWA → 前端拿短效 token 來換一顆
長效裝置 token（存 localStorage）→ 之後 API 全走 X-Device-Token header，
不用再回 Discord 拿新連結。

只有「短效 token」能換發（不收裝置 token）——換發權綁在「剛從 Discord 拿到連結」
這件事上，洩漏的裝置 token 沒辦法自我繁殖。
"""
from fastapi import APIRouter, Query, HTTPException

from auth import validate_report_token, create_device_token

router = APIRouter()


@router.post("/api/device-token")
def issue_device_token(token: str = Query(None), label: str = Query("", max_length=120)):
    """用有效的短效 token 換發長效裝置 token。"""
    if not token or not validate_report_token(token):
        raise HTTPException(status_code=401, detail="短效連結無效或已過期，請回 Discord 用 /美食地圖 重拿。")
    return {"token": create_device_token(label=label)}
