"""Google Places API (New) 薄封裝。I/O 邊界，不單測。"""
import os
import json
import urllib.request
import urllib.parse

from food.regions import parse_address_components

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.addressComponents"
)


def search_text(query: str) -> dict | None:
    """用文字查最相關的一家店。回正規化後的 dict，查無回 None。"""
    key = os.getenv("GOOGLE_PLACES_SERVER_KEY")
    if not key:
        raise RuntimeError("GOOGLE_PLACES_SERVER_KEY 未設定")
    body = json.dumps(
        {"textQuery": query, "languageCode": "zh-TW", "maxResultCount": 1}
    ).encode("utf-8")
    req = urllib.request.Request(
        _SEARCH_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": _FIELD_MASK,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    places = data.get("places") or []
    if not places:
        return None
    p = places[0]
    if not p.get("id"):
        return None  # 沒有 place_id 無法去重/導航，視同查無
    region = parse_address_components(p.get("addressComponents"))
    loc = p.get("location") or {}
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text"),
        "address": p.get("formattedAddress"),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "country": region["country"],
        "city": region["city"],
        "district": region["district"],
    }


def maps_url(place_id: str, name: str = "") -> str:
    """組 Google Maps 連結（官方 Maps URLs api=1 格式，導航/查看用）。

    query 為必填（place_id 找不到時的 fallback）；有店名就帶店名，否則用 place_id 字串墊。
    參考：https://developers.google.com/maps/documentation/urls/get-started
    """
    query = urllib.parse.quote(name or place_id)
    return (
        "https://www.google.com/maps/search/?api=1"
        f"&query={query}&query_place_id={place_id}"
    )


_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"


def fetch_reviews(place_id: str) -> list[dict]:
    """抓 Place Details 的 reviews 欄位（最相關約 5 則）。失敗回 []。"""
    key = os.getenv("GOOGLE_PLACES_SERVER_KEY")
    if not key or not place_id:
        return []
    try:
        req = urllib.request.Request(
            _DETAILS_URL.format(place_id=place_id),
            method="GET",
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "reviews",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return data.get("reviews") or []
    except Exception:
        return []


def caution_for_place_id(place_id: str) -> str:
    """用低星評論做雷點摘要。沒低星回友善訊息；任何失敗回空字串。"""
    from codex_cli import codex_text
    reviews = fetch_reviews(place_id)
    if not reviews:
        return ""
    low_lines: list[str] = []
    for r in reviews:
        rating = r.get("rating") or 0
        text = (r.get("text") or {}).get("text") or r.get("originalText", {}).get("text") or ""
        if rating and rating <= 3 and text:
            low_lines.append(f"({rating}星) {text}")
    if not low_lines:
        return "近期評論沒看到明顯雷點"
    prompt = (
        "以下是 Google 評論的低星留言，請用一句話(<=40字)歸納主要雷點，"
        "台灣口語、不加標題、不列點，直接給文字：\n\n"
        + "\n\n".join(low_lines[:5])
    )
    try:
        return codex_text(prompt).strip()[:200]
    except Exception:
        return ""


def recommended_for_place_id(place_id: str) -> str:
    """從評論萃取『大家推薦點什麼』。沒評論/沒提到餐點/失敗皆回空字串。"""
    from codex_cli import codex_text
    reviews = fetch_reviews(place_id)
    lines = []
    for r in reviews:
        text = (r.get("text") or {}).get("text") or (r.get("originalText") or {}).get("text") or ""
        if text:
            lines.append(text)
    if not lines:
        return ""
    prompt = (
        "以下是某餐廳的 Google 評論。請歸納『大家最常推薦點的餐點』，"
        "只回菜名、用頓號(、)分隔、最多 5 樣，不要解釋、不要標題、不要評分；"
        "評論裡沒提到任何具體餐點就回空字串：\n\n"
        + "\n\n".join(lines[:5])
    )
    try:
        return codex_text(prompt).strip()[:200]
    except Exception:
        return ""


_PHOTO_MEDIA_URL = "https://places.googleapis.com/v1/{name}/media"


def fetch_place_photo(place_id: str, max_px: int = 800) -> tuple[bytes, str] | None:
    """抓該店第一張 Google 照片的 bytes。回 (data, 'jpg') 或 None。"""
    key = os.getenv("GOOGLE_PLACES_SERVER_KEY")
    if not key or not place_id:
        return None
    try:
        # 1) 先拿 photo 的 resource name（field mask = photos）
        req = urllib.request.Request(
            _DETAILS_URL.format(place_id=place_id), method="GET",
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": "photos"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        photos = data.get("photos") or []
        name = (photos[0].get("name") if photos else None)
        if not name:
            return None
        # 2) 下載實際照片 bytes（media endpoint 會轉址到真圖）
        url = _PHOTO_MEDIA_URL.format(name=name) + \
            f"?maxHeightPx={max_px}&key={urllib.parse.quote(key)}"
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = {"image/jpeg": "jpg", "image/png": "png",
               "image/webp": "webp", "image/gif": "gif"}.get(ctype, "jpg")
        return data, ext
    except Exception:
        return None
