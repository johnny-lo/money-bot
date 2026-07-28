"""行政區資料表的自我檢查（純資料，不連 DB）。

這張表是手寫資料，打錯字的風險比邏輯 bug 高 → 靠不變式守住，
而不是逐條人工核對 368 筆。
"""
from food.tw_divisions import (
    TW_CITIES, CITY_ALIASES, TW_DISTRICTS, DISTRICT_ALIASES,
)


def test_有二十二個縣市():
    assert len(TW_CITIES) == 22
    assert len(set(TW_CITIES)) == 22


def test_鄉鎮市區共三百六十八個():
    """中華民國現行行政區劃：368 個鄉鎮市區。少一個就是漏打、多一個就是重複。"""
    assert sum(len(v) for v in TW_DISTRICTS.values()) == 368


def test_每個縣市都有行政區清單():
    assert set(TW_DISTRICTS) == set(TW_CITIES)
    for city, districts in TW_DISTRICTS.items():
        assert districts, f"{city} 沒有任何行政區"


def test_行政區在同一縣市內不重複():
    for city, districts in TW_DISTRICTS.items():
        assert len(set(districts)) == len(districts), f"{city} 有重複行政區"


def test_行政區名一律以區鄉鎮市結尾():
    for city, districts in TW_DISTRICTS.items():
        for d in districts:
            assert d[-1] in "區鄉鎮市", f"{city} 的「{d}」結尾不合法"


def test_一律用台不用臺():
    """D1：儲存格式統一台-form，比對前會先把臺折成台，表裡不能有臺。"""
    for city in TW_CITIES:
        assert "臺" not in city, city
    for city, districts in TW_DISTRICTS.items():
        for d in districts:
            assert "臺" not in d, f"{city}/{d}"


def test_縣市別名指向合法縣市():
    for alias, canonical in CITY_ALIASES.items():
        assert canonical in TW_CITIES, f"{alias} → {canonical} 不是合法縣市"
        assert alias != canonical, f"{alias} 別名指向自己，是多餘的"


def test_升格舊名別名指向該縣市的合法行政區():
    for city, aliases in DISTRICT_ALIASES.items():
        assert city in TW_CITIES, city
        for old, new in aliases.items():
            assert new in TW_DISTRICTS[city], f"{city}: {old} → {new} 不在該縣市"
            assert old != new, f"{city}: {old} 別名指向自己"


def test_升格舊名涵蓋實際踩到的案例():
    """id=69 的地址是 2014 升格前的「中坜市」（簡體），必須認得。"""
    assert DISTRICT_ALIASES["桃園市"]["中壢市"] == "中壢區"
    assert DISTRICT_ALIASES["新北市"]["板橋市"] == "板橋區"
    assert DISTRICT_ALIASES["台中市"]["豐原市"] == "豐原區"
    assert DISTRICT_ALIASES["高雄市"]["鳳山市"] == "鳳山區"
    assert DISTRICT_ALIASES["台南市"]["永康鄉"] == "永康區"


def test_升格舊名不與現行行政區打架():
    """別名的 key 不能剛好是同縣市現行的行政區名，否則查表會蓋掉正解。"""
    for city, aliases in DISTRICT_ALIASES.items():
        current = set(TW_DISTRICTS[city])
        for old in aliases:
            assert old not in current, f"{city} 的「{old}」既是現行區名又是別名"


def test_使用者關心的行政區都在表裡():
    assert "中壢區" in TW_DISTRICTS["桃園市"]
    assert "竹北市" in TW_DISTRICTS["新竹縣"]
    assert "竹東鎮" in TW_DISTRICTS["新竹縣"]
    assert "東區" in TW_DISTRICTS["新竹市"]      # 新竹市 vs 新竹縣 不能糊在一起
    assert "頭份市" in TW_DISTRICTS["苗栗縣"]    # 縣轄市，結尾是市但它是行政區
