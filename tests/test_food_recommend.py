from food.recommend import filter_for_recommendation, sort_recent, pick_random

PLACES = [
    {"name": "A", "country": "台灣", "city": "台中市", "status": "想去", "created_at": "2026-05-01"},
    {"name": "B", "country": "台灣", "city": "台中市", "status": "去過", "created_at": "2026-05-02"},
    {"name": "C", "country": "台灣", "city": "台北市", "status": "想去", "created_at": "2026-05-03"},
    {"name": "D", "country": "日本", "city": "大阪", "status": "想去", "created_at": "2026-05-04"},
]


def test_filter_only_wishlist_and_region():
    out = filter_for_recommendation(PLACES, "台中")
    names = {p["name"] for p in out}
    assert names == {"A"}          # B 已去過、C 在台北、D 在日本


def test_filter_by_country():
    out = filter_for_recommendation(PLACES, "日本")
    assert {p["name"] for p in out} == {"D"}


def test_sort_recent_desc():
    out = sort_recent(PLACES)
    assert [p["name"] for p in out] == ["D", "C", "B", "A"]


def test_pick_random_from_list():
    one = pick_random([PLACES[0]])
    assert one["name"] == "A"


def test_pick_random_empty():
    assert pick_random([]) is None
