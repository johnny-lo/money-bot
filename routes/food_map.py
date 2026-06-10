"""美食地圖：HTML 頁（自驗 token）+ 店家 JSON API + PWA 寫操作（去過/照片）。"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from auth import validate_report_token, require_token
from food.repo import list_places, set_visited
from food.map_data import build_map_places
from food.photos import photos_by_place, list_photos, add_photo, delete_photo

router = APIRouter()

PHOTO_MAX_BYTES = 5 * 1024 * 1024   # 單張上限 5MB（手機照片經瀏覽器通常 1-3MB）
PHOTO_MAX_PER_PLACE = 10            # 每店上限，防磁碟被塞爆

# Content-Type → 存檔副檔名（白名單,不信任檔名）
_CTYPE_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/gif": "gif", "image/heic": "heic",
}


@router.get("/api/food/places", dependencies=[Depends(require_token)])
def api_food_places(status: str = Query(None)):
    """回傳店家清單（每家帶上自己的照片 [{id,url,source}]）。status 選填（想去/去過），省略=全部。"""
    s = status if status in ("想去", "去過") else None
    places = build_map_places(list_places(s))
    photos = photos_by_place()  # {place_id: [{id,url,source},...]} 一次撈,避免 N+1
    for p in places:
        p["photos"] = photos.get(p["id"], [])
    return {"places": places}


class VisitedBody(BaseModel):
    rating: Optional[int] = None
    note: Optional[str] = None


@router.post("/api/food/places/{place_id}/visited", dependencies=[Depends(require_token)])
def api_food_visited(place_id: int, body: VisitedBody):
    """把店家標成「去過」，可帶評分(1-5)/心得。超範圍評分當沒給（與 /去過 slash 一致）。"""
    rating = body.rating if body.rating and 1 <= body.rating <= 5 else None
    note = (body.note or "").strip() or None
    p = set_visited(place_id, rating=rating, note=note)
    if p is None:
        raise HTTPException(status_code=404, detail=f"找不到編號 {place_id}")
    return {"place": p}


@router.post("/api/food/places/{place_id}/photos", dependencies=[Depends(require_token)])
async def api_food_upload_photo(place_id: int, file: UploadFile = File(...)):
    """上傳一張店家照片（PWA 拍照/相簿）。檔案存 media/，DB 記路徑，source='app'。"""
    ext = _CTYPE_EXT.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=415, detail="只收圖片（jpeg/png/webp/gif/heic）")
    if len(list_photos(place_id)) >= PHOTO_MAX_PER_PLACE:
        raise HTTPException(status_code=409, detail=f"這家店照片已達上限 {PHOTO_MAX_PER_PLACE} 張，先刪幾張再傳")
    data = await file.read()
    if len(data) > PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="單張照片上限 5MB")
    if not data:
        raise HTTPException(status_code=400, detail="空檔案")
    photo = add_photo(place_id, data, ext, source="app")
    return {"photo": photo}


@router.delete("/api/food/photos/{photo_id}", dependencies=[Depends(require_token)])
def api_food_delete_photo(photo_id: int):
    """刪一張照片（DB 列 + 檔案）。"""
    if not delete_photo(photo_id):
        raise HTTPException(status_code=404, detail=f"找不到照片 {photo_id}")
    return {"ok": True}


@router.get("/food/map", response_class=HTMLResponse)
def food_map_page(token: str = Query(None)):
    """美食地圖頁面（需有效 token；把 browser key / mapId 注入 HTML）。"""
    if not token or not validate_report_token(token):
        raise HTTPException(status_code=401, detail="無效或過期的連結，請重新用 /美食地圖 取得連結。")
    with open("templates/food_map.html", "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__BROWSER_KEY__", os.getenv("GOOGLE_MAPS_BROWSER_KEY", ""))
    html = html.replace("__MAP_ID__", os.getenv("GOOGLE_MAPS_MAP_ID", "DEMO_MAP_ID"))
    return html
