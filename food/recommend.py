"""美食推薦篩選/排序（純函式，無 I/O）。"""
import random

from food.regions import region_matches


def filter_for_recommendation(places: list[dict], query: str) -> list[dict]:
    """只留『想去』且國家或城市命中查詢的店。"""
    return [
        p for p in places
        if p.get("status") == "想去"
        and region_matches(query, p.get("country"), p.get("city"))
    ]


def sort_recent(places: list[dict]) -> list[dict]:
    """新到舊（依 created_at 字串，ISO 格式可直接字典序比較）。"""
    return sorted(places, key=lambda p: p.get("created_at") or "", reverse=True)


def pick_random(places: list[dict]) -> dict | None:
    """隨機挑一家（選擇困難救星）；空清單回 None。"""
    return random.choice(places) if places else None
