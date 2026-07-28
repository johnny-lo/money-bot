"""把 FoodPlace dict 整形成前端地圖 marker 用的精簡 JSON（純函式，無 I/O）。

決策：含 caution_summary（點 pin 的 InfoWindow 顯示，有值才渲染）；過濾掉無座標的店。
"""
from food.places import maps_url


def build_map_places(places: list[dict]) -> list[dict]:
    """過濾無 lat/lng 的店，整形成 marker 需要的精簡欄位。"""
    out: list[dict] = []
    for p in places:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        place_id = p.get("place_id")
        if place_id:
            url = maps_url(place_id, p.get("name") or "")
        else:
            url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "status": p.get("status"),
            "visited": p.get("status") == "去過",
            "city": p.get("city"),
            "district": p.get("district"),
            "place_id": place_id,
            "lat": lat,
            "lng": lng,
            "cuisine_major": p.get("cuisine_major"),
            "cuisine_minor": p.get("cuisine_minor"),
            # 原始文字仍然帶出去：舊的 PWA 殼（SW 快取）還在讀這個 key
            "cuisine_type": p.get("cuisine_type"),
            "recommended_items": p.get("recommended_items"),
            "my_rating": p.get("my_rating"),
            "my_note": p.get("my_note"),
            "address": p.get("address"),
            "caution_summary": p.get("caution_summary") or "",
            "maps_url": url,
        })
    return out
