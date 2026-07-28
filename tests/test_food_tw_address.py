"""台灣地址文字 → (縣市, 鄉鎮市區) 的純函式測試。

真實地址從 tests/fixtures/food_addresses.json 讀（正式 DB 匯出的 112 筆），
不在測試裡手抄——手抄會抄錯，而且抄的是「我以為的樣子」不是真資料。
逐條案例一律用 id 指名，期望值才看得出在釘什麼陷阱。
"""
import json
import pathlib

import pytest

from food.regions import parse_tw_address, normalize_city, normalize_district
from food.tw_divisions import TW_CITIES, TW_DISTRICTS

_FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "food_addresses.json").read_text(encoding="utf-8")
)
_BY_ID = {r["id"]: r["address"] for r in _FIXTURE}
_TW_ROWS = [r for r in _FIXTURE if r["country"] == "台灣"]


# ---------- 逐條陷阱（每一條都是真實資料裡踩到的） ----------

@pytest.mark.parametrize("place_id, city, district", [
    (79, "新竹市", "東區"),      # 新竹市 vs 新竹縣：不能再糊成「新竹」
    (82, "新竹縣", "竹北市"),    # 縣轄市：結尾是「市」但它是行政區不是縣市
    (89, "新竹縣", "竹東鎮"),    # 鎮，且無里名可依附；Google 給的是 NULL
    (103, "新竹縣", "竹北市"),   # 同上，Google 給 NULL
    (85, "新竹市", "東區"),      # 里名「南市里」開頭像行政區 → 不可貪婪吃成「東區南市」
    (95, "新竹縣", "竹北市"),    # 里名「竹北里」與同址的縣轄市同形
    (45, "桃園市", "中壢區"),    # 里名「中壢里」與行政區同形
    (69, "桃園市", "中壢區"),    # 簡體「桃园市中坜市」+ 2014 升格前舊名
    (17, "台北市", "大安區"),    # 英文倒序地址
    (31, "台北市", "大安區"),    # 英文倒序，且無 No. 前綴
    (78, "苗栗縣", "頭份市"),    # 英文倒序 + 縣轄市 + 6 位郵遞區號
    (102, "台東縣", "台東市"),   # 臺→台，且縣轄市與縣同名
    (109, "新竹縣", "芎林鄉"),   # 「村」不可當行政區
    (108, "新北市", "板橋區"),   # Google 給 NULL
    (107, "台北市", "中山區"),   # 5 位郵遞區號，Google 給 NULL
    (118, "新竹市", "北區"),     # 6 位郵遞區號
    (61, "桃園市", "中壢區"),    # 尾端有垃圾字元
    (114, "台南市", "中西區"),   # 3 字行政區
    (101, "台北市", "中正區"),   # 里名「新營里」是別的縣市的行政區（台南新營區）
    (88, "新竹市", "東區"),      # 里名「新莊里」是別的縣市的行政區（新北新莊區）
    (83, "新竹市", "北區"),
])
def test_真實地址解析(place_id, city, district):
    assert parse_tw_address(_BY_ID[place_id]) == (city, district)


# ---------- 不變式（掃過全部 112 筆） ----------

def test_每筆台灣地址都解得出縣市():
    bad = [r["id"] for r in _TW_ROWS if parse_tw_address(r["address"])[0] is None]
    assert not bad, f"這些 id 解不出縣市：{bad}"


def test_解出的縣市一定在詞彙表裡():
    for r in _TW_ROWS:
        city, _ = parse_tw_address(r["address"])
        assert city in TW_CITIES, f"id={r['id']} 解出非法縣市 {city}"


def test_解出的行政區一定屬於該縣市():
    for r in _TW_ROWS:
        city, district = parse_tw_address(r["address"])
        assert district is None or district in TW_DISTRICTS[city], \
            f"id={r['id']} 的 {district} 不屬於 {city}"


def test_行政區永不是里或村():
    """D3：里比 NULL 更糟——寧可空著，也不要塞一個沒人看得懂的里名。"""
    for r in _TW_ROWS:
        _, district = parse_tw_address(r["address"])
        assert district is None or district[-1] not in "里村", f"id={r['id']} → {district}"


def test_正規輸出可以再解一次得到同樣結果():
    """輸出的是查表正規字串，所以拿它當輸入必須原地不動（冪等）。"""
    for r in _TW_ROWS:
        city, district = parse_tw_address(r["address"])
        assert parse_tw_address(f"{city}{district or ''}") == (city, district)


# ---------- 邊界 ----------

def test_國外地址不硬塞成台灣():
    assert parse_tw_address("日本〒160-0022 東京都新宿区新宿３丁目") == (None, None)
    assert parse_tw_address("123 Main St, Seattle, WA") == (None, None)


def test_空輸入():
    assert parse_tw_address(None) == (None, None)
    assert parse_tw_address("") == (None, None)
    assert parse_tw_address("   ") == (None, None)


def test_只有縣市沒有行政區():
    assert parse_tw_address("台灣桃園市") == ("桃園市", None)


def test_路名含縣市字樣不會搶走縣市():
    """最左命中：地址一定是縣市在前，路名在後。"""
    assert parse_tw_address("100台灣台北市中正區桃園街1號") == ("台北市", "中正區")


# ---------- normalize_city / normalize_district ----------

def test_縣市正規化():
    assert normalize_city("臺北市") == "台北市"
    assert normalize_city("桃园市") == "桃園市"       # 簡體
    assert normalize_city("桃園縣") == "桃園市"       # 升格舊名
    assert normalize_city("台北縣") == "新北市"
    assert normalize_city("桃園") == "桃園市"         # 無歧義簡稱
    assert normalize_city("台東") == "台東縣"


def test_歧義簡稱不猜():
    """新竹/嘉義 同時可能是市或縣 → 回空字串，讓呼叫端知道解不出。"""
    assert normalize_city("新竹") == ""
    assert normalize_city("嘉義") == ""


def test_非台灣縣市回空():
    assert normalize_city("東京") == ""
    assert normalize_city("") == ""
    assert normalize_city(None) == ""


def test_行政區正規化限定在該縣市內():
    assert normalize_district("新竹縣", "竹北市") == "竹北市"
    assert normalize_district("桃園市", "中壢市") == "中壢區"   # 升格舊名
    assert normalize_district("桃園市", "平镇区") == "平鎮區"   # 簡體
    assert normalize_district("台北市", "竹北市") == ""         # 不屬於這個縣市
    assert normalize_district("新竹縣", "竹北里") == ""         # 里不是行政區
    assert normalize_district("新竹縣", "") == ""
