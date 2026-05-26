"""地名正規化與比對（純函式，無 I/O）。"""

# 別名 → 正規顯示名（key 一律小寫比對）
_CITY_ALIAS = {
    "taichung": "台中市", "台中": "台中市", "臺中": "台中市", "台中市": "台中市", "臺中市": "台中市",
    "taipei": "台北市", "台北": "台北市", "臺北": "台北市", "台北市": "台北市", "臺北市": "台北市",
    "kaohsiung": "高雄市", "高雄": "高雄市", "高雄市": "高雄市",
    "tainan": "台南市", "台南": "台南市", "臺南": "台南市", "台南市": "台南市",
    "tokyo": "東京", "東京": "東京", "東京都": "東京",
    "osaka": "大阪", "大阪": "大阪", "大阪市": "大阪",
    "seoul": "首爾", "首爾": "首爾",
}
_COUNTRY_ALIAS = {
    "taiwan": "台灣", "台灣": "台灣", "臺灣": "台灣", "tw": "台灣",
    "japan": "日本", "日本": "日本", "jp": "日本",
    "korea": "韓國", "south korea": "韓國", "韓國": "韓國", "kr": "韓國",
}
_SUFFIXES = ["City", "city", "市", "縣", "都", "府", "県", "区", "區"]


def _strip_suffix(s: str) -> str:
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)].strip()
    return s.strip()


def canon(s: str | None) -> str:
    """正規化地名：先查別名，未命中則去行政後綴再查一次。回正規名或去後綴字串。"""
    if not s:
        return ""
    key = s.strip().lower()
    if key in _CITY_ALIAS:
        return _CITY_ALIAS[key]
    if key in _COUNTRY_ALIAS:
        return _COUNTRY_ALIAS[key]
    stripped = _strip_suffix(s.strip())
    k2 = stripped.lower()
    if k2 in _CITY_ALIAS:
        return _CITY_ALIAS[k2]
    if k2 in _COUNTRY_ALIAS:
        return _COUNTRY_ALIAS[k2]
    return stripped


def region_matches(query: str, country: str | None, city: str | None) -> bool:
    """查詢字串是否命中店家的國家或城市（正規化後等於或互相包含）。"""
    q = canon(query)
    if not q:
        return False
    for field in (country, city):
        c = canon(field)
        if c and (q == c or q in c or c in q):
            return True
    return False


def parse_address_components(components: list[dict] | None) -> dict:
    """Places (New) addressComponents → {country, city, district}。

    component 形如 {"longText":..., "shortText":..., "types":[...]}。
    city 優先序：locality > administrative_area_level_1 > administrative_area_level_2。
    """
    by_type: dict[str, str] = {}
    for comp in components or []:
        text = comp.get("longText") or comp.get("shortText")
        if not text:
            continue
        for t in comp.get("types", []):
            by_type.setdefault(t, text)

    country = canon(by_type.get("country"))
    city = canon(
        by_type.get("locality")
        or by_type.get("administrative_area_level_1")
        or by_type.get("administrative_area_level_2")
    )
    district = by_type.get("sublocality") or by_type.get("administrative_area_level_3")
    return {
        "country": country or None,
        "city": city or None,
        "district": district,
    }
