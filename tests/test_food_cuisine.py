"""料理兩層分類（大類 + 細類）的純函式測試。

三層優先序（這是本模組唯一的設計決策，其他都是查表）：
  A 店型（咖啡甜點/飲料冰品）> B 菜系國別 > C 弱品類（火鍋/燒烤/早午餐/酒吧）
只在判讀 cuisine_type（描述「這家店是什麼店」）時套用；
判讀店名/推薦菜（描述「這家店賣什麼菜」）時純看最左命中——
否則任何在推薦菜裡提到一塊蛋糕的餐廳都會變成咖啡甜點店。
"""
import pytest

from food.cuisine import MAJORS, normalize_major, classify


def test_剛好十二個大類():
    assert len(MAJORS) == 12
    assert len(set(MAJORS)) == 12


# ── 使用者定案的七條規則 ──────────────────────────────────────

@pytest.mark.parametrize("raw, major, minor", [
    ("拉麵", "日式", "拉麵"),
    ("日式燒肉", "日式", "燒肉"),              # 菜系勝過燒烤；細類不重複已在大類的「日式」
    ("牛肉麵", "台式", "牛肉麵"),
    ("滷肉飯", "台式", "滷肉飯"),
    ("法式甜點", "咖啡甜點", "法式甜點"),      # 店型勝過菜系：你去甜點店是為了甜點
    ("印度咖哩", "東南亞", "印度咖哩"),        # 12 類沒有南亞桶，落最近的亞洲異國
    ("費城起司牛肉三明治", "西式", "費城起司牛肉三明治"),
])
def test_使用者定案規則(raw, major, minor):
    assert classify(raw) == (major, minor)


def test_國別勝過弱品類():
    assert classify("韓式燒肉")[0] == "韓式"
    assert classify("美式BBQ燒烤")[0] == "西式"
    assert classify("日式刨冰、甜點")[0] == "飲料冰品"   # 店型仍勝過國別
    assert classify("燒肉")[0] == "燒烤"                # 沒有國別才落弱品類
    assert classify("鍋物")[0] == "火鍋"


def test_菜系優先套用到火鍋():
    """重慶麻辣火鍋是川菜館，不是「火鍋」這個品類——與日式燒肉同一條規則。"""
    assert classify("重慶麻辣火鍋")[0] == "中式"


# ── 複合值（真實資料裡一格塞好幾種）──────────────────────────

@pytest.mark.parametrize("raw, major", [
    ("咖啡、早午餐", "咖啡甜點"),
    ("甜品、豆花、仙草、飲品", "咖啡甜點"),
    ("肉圓、大腸麵線、臭豆腐", "台式"),
    ("滷肉飯、當歸羊肉", "台式"),
    ("咖啡廳、下午茶、簡餐", "咖啡甜點"),
    ("歐式麵包、早午餐", "咖啡甜點"),
])
def test_複合值取最左命中(raw, major):
    assert classify(raw)[0] == major


def test_全形逗號與空白也切得開():
    assert classify("咖啡，早午餐")[0] == "咖啡甜點"
    assert classify("  拉麵  ")[0] == "日式"


def test_異體字折疊():
    assert classify("咖喱") == classify("咖哩")
    assert classify("義式冰淇淋")[0] == classify("义式冰淇淋")[0]


# ── 垃圾值：真實資料裡佔 5 筆，完全沒有分類訊號 ────────────────

@pytest.mark.parametrize("raw", ["小館", "食堂", "餐廳", "家常料理", "料理", ""])
def test_垃圾值不猜(raw):
    assert classify(raw) == ("", "")


def test_垃圾值仍會退到店名():
    """cuisine_type 是垃圾不代表放棄——店名還有機會。"""
    assert classify("餐廳", name="極清拉麵")[0] == "日式"


def test_國別詞後面只剩垃圾時細類留空():
    assert classify("中式料理") == ("中式", "")
    assert classify("台式小吃") == ("台式", "小吃")


def test_大類沒收下國別資訊時細類要留著():
    """剝前綴的前提是「大類已經講了同一件事」，否則會把資訊弄丟。

    日式燒肉 → 大類就是「日式」，細類再寫一次沒意義 → 剝成「燒肉」。
    泰式料理 → 大類是「東南亞」（涵蓋泰/越/馬/印度），剝掉「泰式」就再也
    看不出是泰國菜 → 必須留著。
    """
    assert classify("泰式料理") == ("東南亞", "泰式料理")
    assert classify("美式BBQ燒烤") == ("西式", "美式BBQ燒烤")
    assert classify("日式燒肉") == ("日式", "燒肉")


# ── 店名 / 推薦菜 fallback ─────────────────────────────────────

@pytest.mark.parametrize("name, major", [
    ("極清拉麵", "日式"),
    ("是吉祥精緻火鍋館", "火鍋"),
    ("不眠深夜咖啡廳", "咖啡甜點"),
    ("五燈獎豬腳飯", "台式"),
    ("食霸 重慶麻辣火鍋", "中式"),
    ("唐宮蒙古烤肉酸菜白肉餐廳", "中式"),
    ("山上走走 日式無菜單燒肉專門店", "日式"),
])
def test_店名推得出大類(name, major):
    assert classify("", name=name)[0] == major


def test_推薦菜補位():
    assert classify("", name="莊二姐的廚房", items="打拋豬、叻沙、鹽焗雞、滷肉飯")[0] == "東南亞"
    assert classify("", name="英雄塚", items="生魚片")[0] == "日式"


def test_漢堡店陷阱():
    """真實資料 id=39：推薦菜裡有「中式煎餅」，但這是漢堡店。

    店名/推薦菜走純最左命中（不套店型優先），最左的是「牛排」→ 西式。
    若在這裡也套 A>B>C 分層，任何提到蛋糕的餐廳都會被歸成咖啡甜點店。
    """
    got = classify("", name="肉球尼尼Meatball Nini",
                   items="起司牛排漢堡、番茄燉雞歐姆蛋、中式煎餅、魚漢堡")
    assert got[0] == "西式"


def test_推薦菜提到甜點不會蓋掉主餐():
    got = classify("", name="小事廚房",
                   items="鮪魚腹、烤茄子、紅蟳義大利麵、巴斯克蛋糕")
    assert got[0] == "西式"


def test_細類不從菜單捏造():
    """店名/推薦菜推出來的只放命中的關鍵字，不把整串菜單塞進細類。"""
    _, minor = classify("", name="極清拉麵")
    assert minor == "拉麵"


def test_完全沒訊號就留空():
    assert classify("", name="拾旅。食") == ("", "")
    assert classify("", name="KAORI Dining") == ("", "")
    assert classify(None) == ("", "")


# ── normalize_major：持久化邊界的詞彙表守門員（D7 第三層防線）──

def test_別名折疊():
    assert normalize_major("日本料理") == "日式"
    assert normalize_major("韓國料理") == "韓式"
    assert normalize_major("西餐") == "西式"
    assert normalize_major(" 日式 ") == "日式"


def test_越界值一律清成空字串():
    for bad in ["西班牙菜", "['日式']", "Japanese", "其他", "隨便", "", None, "日式料理店啦"]:
        assert normalize_major(bad) == ""


def test_詞彙表成員檢查是全稱不變式():
    """不管餵什麼進去，出來的只可能是 12 大類之一或空字串。"""
    for s in ["日式", "火鍋", "亂碼🍜", "台", "咖啡甜點", "12", "SELECT *"]:
        assert normalize_major(s) in set(MAJORS) | {""}


def test_classify的大類永遠合法():
    for raw in ["拉麵", "小館", "亂七八糟的東西", "", "冰室", "鐵板燒", "麵食", "豆花"]:
        major, _ = classify(raw)
        assert major in set(MAJORS) | {""}


# ── 爭議條目：釘死而不是留模糊 ────────────────────────────────

@pytest.mark.parametrize("raw, major", [
    ("冰室", "中式"),        # 港式冰室是茶餐廳，不是冰店
    ("鐵板燒", "燒烤"),
    ("豆花", "台式"),
    ("麵包店", "咖啡甜點"),
    ("餐酒館", "酒吧餐酒館"),
    ("早午餐", "早午餐"),
    ("板條", "台式"),
    ("炒飯", "中式"),
])
def test_爭議條目(raw, major):
    assert classify(raw)[0] == major


def test_麵食太籠統不猜():
    """「麵食」可能是牛肉麵店也可能是刀削麵館 —— 讓店名決定比硬猜好。"""
    assert classify("麵食")[0] == ""
