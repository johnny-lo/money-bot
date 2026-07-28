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
    assert out["city"] == "桃園市"      # D1：儲存格式是全名，不再去後綴
    assert out["district"] == "中壢區"


# ── 台灣列拒收里/村（D3）────────────────────────────────────────

def test_parse_address_components_台灣拒收里():
    """Google 常把 sublocality 給成里名（實測 105/112 筆）。里比 None 更糟。"""
    comps = [
        {"longText": "台灣", "types": ["country"]},
        {"longText": "桃園市", "types": ["administrative_area_level_1"]},
        {"longText": "興南里", "types": ["sublocality"]},
    ]
    out = parse_address_components(comps)
    assert out["city"] == "桃園市"
    assert out["district"] is None


def test_parse_address_components_台灣行政區優先於里():
    comps = [
        {"longText": "台灣", "types": ["country"]},
        {"longText": "桃園市", "types": ["administrative_area_level_1"]},
        {"longText": "興南里", "types": ["sublocality"]},
        {"longText": "中壢區", "types": ["administrative_area_level_3"]},
    ]
    assert parse_address_components(comps)["district"] == "中壢區"


# ── resolve_region：台灣以地址文字為單一真相（D4）──────────────

_TW_COMPS = [
    {"longText": "台灣", "types": ["country"]},
    {"longText": "桃園市", "types": ["administrative_area_level_1"]},
    {"longText": "興南里", "types": ["sublocality"]},
]


def test_resolve_region_地址文字勝過components():
    from food.regions import resolve_region
    out = resolve_region("320台灣桃園市中壢區興南里永樂街97號", _TW_COMPS)
    assert out == {"country": "台灣", "city": "桃園市", "district": "中壢區"}


def test_resolve_region_地址解不出才退回components():
    from food.regions import resolve_region
    out = resolve_region("", _TW_COMPS)
    assert out["city"] == "桃園市"
    assert out["district"] is None      # 里被拒收


def test_resolve_region_沒有components也能靠地址():
    from food.regions import resolve_region
    out = resolve_region("302台灣新竹縣竹北市嘉興路181號", None)
    assert out == {"country": "台灣", "city": "新竹縣", "district": "竹北市"}


def test_resolve_region_國外走components不碰台灣邏輯():
    from food.regions import resolve_region
    comps = [
        {"longText": "Japan", "types": ["country"]},
        {"longText": "Tokyo", "types": ["locality"]},
        {"longText": "新宿区", "types": ["sublocality"]},
    ]
    out = resolve_region("日本〒160-0022 東京都新宿区新宿３丁目", comps)
    assert out == {"country": "日本", "city": "東京", "district": "新宿區"}


# ── D2 釘樁：city 改成全名後，/美食推薦 必須照常運作 ──────────────
# region_matches 是靠 canon() 的 _strip_suffix「剛好」成立的，
# 不釘住的話未來有人改 canon 就會無聲弄壞既有查詢。

def test_region_matches_全名縣市仍然命中():
    assert region_matches("桃園", country="台灣", city="桃園市") is True
    assert region_matches("新竹", country="台灣", city="新竹市") is True
    assert region_matches("新竹", country="台灣", city="新竹縣") is True
    assert region_matches("台北", country="台灣", city="台北市") is True


def test_region_matches_修好台東():
    """既有 bug：canon("臺東")="臺東" vs canon("台東")="台東" 比不中 → 查台東永遠回空。"""
    assert region_matches("台東", country="台灣", city="台東縣") is True
    assert region_matches("臺東", country="台灣", city="台東縣") is True


def test_region_matches_命中行政區():
    assert region_matches("中壢", "台灣", "桃園市", "中壢區") is True
    assert region_matches("竹北", "台灣", "新竹縣", "竹北市") is True
    assert region_matches("竹東", "台灣", "新竹縣", "竹北市") is False


def test_region_matches_帶後綴就要精確():
    """使用者打「新竹市」是明確指定 → 不該撈到新竹縣的店。"""
    assert region_matches("新竹市", "台灣", "新竹市") is True
    assert region_matches("新竹市", "台灣", "新竹縣") is False
    assert region_matches("新竹縣", "台灣", "新竹市") is False


def test_canon_不把地名剝成單一個字():
    """「東區」剝成「東」之後，規則 3 的雙向包含會讓「台東」命中所有東區的店。

    單字不是地名 —— 剝到只剩一個字就別剝。
    """
    assert canon("東區") == "東區"
    assert canon("南區") == "南區"
    assert canon("中區") == "中區"
    assert canon("中壢區") == "中壢"      # 剝完還有兩個字，照剝
    assert canon("竹東鎮") == "竹東鎮"    # 鎮/鄉 本來就不在後綴表裡，靠包含比對命中


def test_region_matches_台東不會撈到新竹市東區():
    assert region_matches("台東", "台灣", "新竹市", "東區") is False
    assert region_matches("竹東", "台灣", "新竹市", "東區") is False
    assert region_matches("台東", "台灣", "台東縣", "台東市") is True
    assert region_matches("竹東", "台灣", "新竹縣", "竹東鎮") is True


def test_region_matches_不帶後綴維持刻意的模糊():
    """已知取捨：打「新竹」兩邊都撈。這是現有契約，釘住它是刻意行為而非未爆彈。"""
    assert region_matches("新竹", "台灣", "新竹市") is True
    assert region_matches("新竹", "台灣", "新竹縣") is True
