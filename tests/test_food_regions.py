from food.regions import canon, region_matches, parse_address_components


def test_canon_taiwan_city_aliases():
    assert canon("台中") == "台中市"
    assert canon("台中市") == "台中市"
    assert canon("臺中市") == "台中市"
    assert canon("Taichung City") == "台中市"


def test_canon_country_and_foreign_city():
    assert canon("日本") == "日本"
    assert canon("Japan") == "日本"
    assert canon("東京都") == "東京"
    assert canon("Osaka") == "大阪"


def test_canon_empty():
    assert canon(None) == ""
    assert canon("") == ""


def test_region_matches_taiwan_city():
    assert region_matches("台中", country="台灣", city="台中市") is True
    assert region_matches("台北", country="台灣", city="台中市") is False


def test_region_matches_country_and_foreign_city():
    assert region_matches("日本", country="日本", city="東京") is True
    assert region_matches("大阪", country="日本", city="大阪") is True
    assert region_matches("首爾", country="日本", city="大阪") is False


def test_parse_address_components_taiwan():
    comps = [
        {"longText": "台灣", "types": ["country"]},
        {"longText": "臺中市", "types": ["administrative_area_level_1"]},
        {"longText": "西區", "types": ["administrative_area_level_3"]},
    ]
    out = parse_address_components(comps)
    assert out["country"] == "台灣"
    assert out["city"] == "台中市"
    assert out["district"] == "西區"


def test_parse_address_components_prefers_locality():
    comps = [
        {"longText": "Japan", "types": ["country"]},
        {"longText": "Tokyo", "types": ["locality"]},
        {"longText": "Kanto", "types": ["administrative_area_level_1"]},
    ]
    out = parse_address_components(comps)
    assert out["country"] == "日本"
    assert out["city"] == "東京"
