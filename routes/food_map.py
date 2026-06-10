"""美食地圖：HTML 頁（自驗 token）+ 店家 JSON API（Depends token）。"""
import os
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse

from auth import validate_report_token, require_token
from food.repo import list_places
from food.map_data import build_map_places
from food.photos import photos_by_place

router = APIRouter()


@router.get("/api/food/places", dependencies=[Depends(require_token)])
def api_food_places(status: str = Query(None)):
    """回傳店家清單（每家帶上自己的照片）。status 選填（想去/去過），省略=全部。"""
    s = status if status in ("想去", "去過") else None
    places = build_map_places(list_places(s))
    photos = photos_by_place()  # {place_id: [url,...]} 一次撈,避免 N+1
    for p in places:
        p["photos"] = photos.get(p["id"], [])
    return {"places": places}


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
