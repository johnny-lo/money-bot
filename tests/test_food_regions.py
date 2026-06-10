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


# ── 繁簡正規化（Google Places 偶爾回簡體地名）──────────────────

def test_canon_folds_simplified_to_traditional():
    from food.regions import canon
    assert canon("桃园") == "桃園"
    assert canon("桃园市") == "桃園"          # 折繁 + 去行政後綴
    assert canon("桃园") == canon("桃園")     # 繁簡殊途同歸
    assert canon("东京") == "東京"            # 折繁後命中既有別名表


def test_to_traditional_district():
    from food.regions import to_traditional
    assert to_traditional("中坜区") == "中壢區"
    assert to_traditional("西區") == "西區"   # 已是繁體不動
    assert to_traditional("") == ""


def test_region_matches_across_scripts():
    from food.regions import region_matches
    assert region_matches("桃園", country="台灣", city="桃园") is True


def test_parse_address_components_folds_district():
    from food.regions import parse_address_components
    comps = [
        {"longText": "台湾", "types": ["country"]},
        {"longText": "桃园市", "types": ["administrative_area_level_1"]},
        {"longText": "中坜区", "types": ["administrative_area_level_3"]},
    ]
    out = parse_address_components(comps)
    assert out["country"] == "台灣"
    assert out["city"] == "桃園"
    assert out["district"] == "中壢區"
