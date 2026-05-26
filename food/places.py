"""Google Places API (New) 薄封裝。I/O 邊界，不單測。"""
import os
import json
import urllib.request

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


def maps_url(place_id: str) -> str:
    """由 place_id 組 Google Maps 連結（導航/查看用）。"""
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"
