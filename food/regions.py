"""地名正規化與比對（純函式，無 I/O）。

兩套正規化，別搞混：
- `canon()`：**模糊比對鍵**（去行政後綴），只給 `region_matches` 用。不是儲存格式。
- `normalize_city()` / `normalize_district()` / `parse_tw_address()`：**儲存格式**，
  一律 22 縣市全名 + 合法鄉鎮市區（台-form）。台灣列的真相來源是地址文字，見 `resolve_region`。
"""
from food.tw_divisions import (
    TW_CITIES, CITY_ALIASES, TW_DISTRICTS, DISTRICT_ALIASES,
)

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

# 簡→繁字元表（Google Places 偶爾回簡體地名，例：桃园/中坜区）。
# 只收地名常用字，不裝 OpenCC 整套——這個量級查表就夠。
_S2T = str.maketrans({
    "园": "園", "湾": "灣", "县": "縣", "岛": "島", "东": "東", "门": "門",
    "马": "馬", "龙": "龍", "凤": "鳳", "兰": "蘭", "义": "義", "乡": "鄉",
    "镇": "鎮", "区": "區", "桥": "橋", "滨": "濱", "苏": "蘇", "广": "廣",
    "庄": "莊", "头": "頭", "屿": "嶼", "阳": "陽", "云": "雲", "营": "營",
    "兴": "興", "万": "萬", "丰": "豐", "双": "雙", "内": "內", "关": "關",
    "圆": "圓", "莲": "蓮", "坜": "壢", "冈": "岡", "旧": "舊", "静": "靜",
    "沪": "滬", "杨": "楊", "陈": "陳", "刘": "劉", "张": "張", "黄": "黃",
    "宁": "寧", "济": "濟", "汉": "漢", "锦": "錦", "钱": "錢", "贵": "貴",
})


# 臺→台。**方向與 _S2T 相反**（那張是簡→繁），故意分開兩張表：
# 混在一起下一個讀的人會以為「臺」是簡體字。
_T2T = str.maketrans({"臺": "台"})


def to_traditional(s: str | None) -> str:
    """地名簡體字折成繁體（查表，非整套轉換）。"""
    return (s or "").translate(_S2T)


def fold(s: str | None) -> str:
    """折成查表用的統一形式：簡→繁 + 臺→台。"""
    return to_traditional(s).translate(_T2T)


def _strip_suffix(s: str) -> str:
    """去掉行政後綴，但**剝完至少要留兩個字**。

    「東區」剝成「東」之後，region_matches 規則 3 的雙向包含會讓「台東」
    命中所有東區的店。單一個字不是地名。
    """
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) - len(suf) >= 2:
            return s[: -len(suf)].strip()
    return s.strip()


def canon(s: str | None) -> str:
    """正規化地名：先查別名，未命中則去行政後綴再查一次。回正規名或去後綴字串。"""
    if not s:
        return ""
    s = to_traditional(s)
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


# ── 儲存格式：縣市 / 鄉鎮市區（台灣專用）────────────────────────

# 正名與別名合成一張查詢表（別名含升格舊名與無歧義簡稱）
_CITY_LOOKUP: dict[str, str] = {**{c: c for c in TW_CITIES}, **CITY_ALIASES}


def normalize_city(s: str | None) -> str:
    """任意寫法 → 22 縣市全名（台-form）。不是台灣縣市就回空字串。"""
    return _CITY_LOOKUP.get(fold(s).strip(), "")


def normalize_district(city: str | None, s: str | None) -> str:
    """→ 該縣市底下的合法鄉鎮市區。不屬於這個縣市（含里/村）一律回空字串。"""
    if city not in TW_DISTRICTS:
        return ""
    d = fold(s).strip()
    if not d:
        return ""
    if d in TW_DISTRICTS[city]:
        return d
    return DISTRICT_ALIASES.get(city, {}).get(d, "")


def _district_candidates(city: str) -> tuple[str, ...]:
    return tuple(TW_DISTRICTS[city]) + tuple(DISTRICT_ALIASES.get(city, {}))


def parse_tw_address(address: str | None) -> tuple[str | None, str | None]:
    """台灣地址文字 → (縣市, 鄉鎮市區)。解不出的部分回 None。

    縣市：掃最左出現、同位取最長 —— 用全名比對，`新竹縣竹北市` 天然不含子字串 `新竹市`。
    行政區：對縣市 token 的**後方做錨定前綴比對**（正常順序），沒中才對**前方做後綴比對**
    （Google 偶爾回英文倒序地址）。

    為什麼錨定而不用 regex 掃：`新竹市東區南市里勝利路` —— 錨在開頭只會比中「東區」，
    永遠碰不到「南市」；任何 `[區鄉鎮市]` 掃描式 regex 都會吃成「東區南市」。
    里名與行政區同形在真實資料裡是常態（中壢區中壢里、竹北市竹北里），不是特例。
    """
    s = fold(address).strip()
    if not s:
        return None, None

    best = None   # (最左位置, -長度) 越小越優先
    for token, canonical in _CITY_LOOKUP.items():
        i = s.find(token)
        if i < 0:
            continue
        key = (i, -len(token))
        if best is None or key < best[0]:
            best = (key, token, canonical)
    if best is None:
        return None, None

    (idx, _), token, city = best
    after, before = s[idx + len(token):], s[:idx]

    hit = ""
    for cand in _district_candidates(city):
        if after.startswith(cand) and len(cand) > len(hit):
            hit = cand
    if not hit:
        for cand in _district_candidates(city):
            if before.endswith(cand) and len(cand) > len(hit):
                hit = cand
    # 回傳查表的正規字串（不是比中的原文）→ 簡體/臺/升格舊名的差異在此消失
    return city, (normalize_district(city, hit) or None)


def region_matches(query: str, country: str | None, city: str | None,
                   district: str | None = None) -> bool:
    """查詢字串是否命中店家的國家/縣市/行政區。

    三條規則，由嚴到寬：
    1. 折字後與任一欄位**全名相等** → 中。
    2. 查詢自帶「市/縣」後綴＝使用者明確指定 → 只認全名，不再模糊比
       （`新竹市` 不該撈到新竹縣的店）。
    3. 否則 canon 後互相包含（沿用舊行為，只是多比一個 district）
       → `中壢` 命中 `中壢區`、`竹北` 命中 `竹北市`。

    `district` 給預設值，舊呼叫端不改也不會壞。
    """
    q_raw = fold(query).strip()
    if not q_raw:
        return False
    fields = (country, city, district)

    for f in fields:
        if f and fold(f).strip() == q_raw:
            return True
    if q_raw.endswith(("市", "縣")):
        return False

    q = canon(q_raw)
    if not q:
        return False
    for f in fields:
        c = canon(f)
        if c and (q == c or q in c or c in q):
            return True
    return False


def _components_by_type(components: list[dict] | None) -> dict[str, str]:
    """component 形如 {"longText":..., "shortText":..., "types":[...]} → {type: text}。"""
    by_type: dict[str, str] = {}
    for comp in components or []:
        text = comp.get("longText") or comp.get("shortText")
        if not text:
            continue
        for t in comp.get("types", []):
            by_type.setdefault(t, text)
    return by_type


def parse_address_components(components: list[dict] | None) -> dict:
    """Places (New) addressComponents → {country, city, district}。

    台灣：city 走 `normalize_city`（全名），district 只收該縣市的合法鄉鎮市區
    （administrative_area_level_3 優先，sublocality 是備援）——里/村一律拒收，寧可 None。
    國外：維持原行為（locality > aal1 > aal2 過 canon；district 用 sublocality）。
    """
    by_type = _components_by_type(components)
    country = canon(by_type.get("country"))
    aal1 = by_type.get("administrative_area_level_1")
    aal2 = by_type.get("administrative_area_level_2")
    aal3 = by_type.get("administrative_area_level_3")
    locality = by_type.get("locality")
    sublocality = by_type.get("sublocality")

    if country == "台灣":
        # 台灣的縣市一律在 aal1；locality 可能是縣轄市（竹北市），那是行政區不是縣市
        city = normalize_city(aal1) or normalize_city(aal2) or normalize_city(locality)
        district = normalize_district(city, aal3) or normalize_district(city, sublocality)
    else:
        city = canon(locality or aal1 or aal2)
        district = to_traditional(sublocality or aal3)

    return {
        "country": country or None,
        "city": city or None,
        "district": district or None,
    }


def resolve_region(address: str | None, components: list[dict] | None) -> dict:
    """地址文字 + addressComponents → {country, city, district}。**唯一入口。**

    台灣以**地址文字為單一真相**：實測同樣兩個縣市，Google 對某些店給得出行政區、
    對另一些給 NULL，竹北市/竹東鎮更是從沒給過 —— components 的行政區不可靠。
    地址文字解不出才退回 components。國外完全走 components（那條路徑一字不動）。
    """
    base = parse_address_components(components)
    if base["country"] and base["country"] != "台灣":
        return base

    city, district = parse_tw_address(address)
    if city:
        return {
            "country": base["country"] or "台灣",
            "city": city,
            "district": district,
        }
    return base
