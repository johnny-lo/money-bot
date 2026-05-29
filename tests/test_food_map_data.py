from food.map_data import build_map_places


def test_filters_out_no_coordinates():
    places = [
        {"id": 1, "name": "A", "status": "想去", "lat": 25.0, "lng": 121.5, "place_id": "p1"},
        {"id": 2, "name": "B", "status": "想去", "lat": None, "lng": 121.5, "place_id": "p2"},
        {"id": 3, "name": "C", "status": "想去", "lat": 25.0, "lng": None, "place_id": "p3"},
    ]
    out = build_map_places(places)
    assert [p["id"] for p in out] == [1]


def test_visited_bool_from_status():
    places = [
        {"id": 1, "name": "A", "status": "去過", "lat": 25.0, "lng": 121.5, "place_id": "p1"},
        {"id": 2, "name": "B", "status": "想去", "lat": 25.1, "lng": 121.6, "place_id": "p2"},
    ]
    out = build_map_places(places)
    assert out[0]["visited"] is True
    assert out[1]["visited"] is False


def test_maps_url_uses_place_id_when_present():
    out = build_map_places([
        {"id": 1, "name": "鼎泰豐", "status": "想去", "lat": 25.0, "lng": 121.5, "place_id": "ChIJ_abc"},
    ])
    assert "query_place_id=ChIJ_abc" in out[0]["maps_url"]


def test_maps_url_fallback_to_coords_when_no_place_id():
    out = build_map_places([
        {"id": 1, "name": "無 id 店", "status": "想去", "lat": 25.5, "lng": 121.2, "place_id": None},
    ])
    assert "query=25.5,121.2" in out[0]["maps_url"]
    assert "query_place_id" not in out[0]["maps_url"]


def test_caution_summary_passed_through():
    out = build_map_places([
        {"id": 1, "name": "A", "status": "想去", "lat": 25.0, "lng": 121.5,
         "place_id": "p1", "caution_summary": "尖峰排隊久"},
    ])
    assert out[0]["caution_summary"] == "尖峰排隊久"


def test_caution_summary_defaults_empty_when_absent():
    out = build_map_places([
        {"id": 1, "name": "A", "status": "想去", "lat": 25.0, "lng": 121.5, "place_id": "p1"},
    ])
    assert out[0]["caution_summary"] == ""


def test_output_fields_and_empty():
    assert build_map_places([]) == []
    out = build_map_places([
        {"id": 7, "name": "店", "status": "想去", "lat": 25.0, "lng": 121.5, "place_id": "p1",
         "cuisine_type": "拉麵", "recommended_items": "豚骨", "my_rating": 4,
         "my_note": "讚", "address": "台北市", "caution_summary": "雷"},
    ])
    assert set(out[0].keys()) == {
        "id", "name", "status", "visited", "lat", "lng", "cuisine_type",
        "recommended_items", "my_rating", "my_note", "address", "caution_summary", "maps_url",
    }
