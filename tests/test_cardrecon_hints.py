from datetime import date

from cardrecon import hints
from cardrecon.types import Charge, TxHint

D = date(2026, 10, 3)


def ch(amount, d=D, card="1234", region="TW", n=0):
    return Charge(source="sinopac_daily", card_last4=card, charge_date=d, amount=amount, line_no=n, region=region)


def tx(key, amount, d=D, label="某店"):
    return TxHint(key=key, tx_date=d, amount=amount, label=label)


def test_GROUPS順序():
    assert [k for k, _ in hints.GROUPS] == ["near", "subscription", "overseas", "small", "other"]
    assert dict(hints.GROUPS)["near"] == "可能記過（帳上有近似紀錄）"


def test_near_miss_前後一天與金額門檻():
    c = ch(1000)
    assert hints.near_miss(c, [tx("a", 1100, date(2026, 10, 4))]).key == "a"      # 10% 邊界
    assert hints.near_miss(c, [tx("a", 1101)]) is None                           # 超過 10%
    assert hints.near_miss(c, [tx("a", 900, date(2026, 10, 2))]).key == "a"
    assert hints.near_miss(ch(50), [tx("a", 60)]).key == "a"                     # 至少 10 元
    assert hints.near_miss(ch(50), [tx("a", 61)]) is None


def test_near_miss_差兩天_金額相同_非正數都不算():
    c = ch(1000)
    assert hints.near_miss(c, [tx("a", 1010, date(2026, 10, 5))]) is None
    assert hints.near_miss(c, [tx("a", 1000)]) is None
    assert hints.near_miss(ch(5), [tx("a", -3), tx("b", 0)]) is None


def test_near_miss_平手順序():
    c = ch(1000)
    # 金額差優先
    assert hints.near_miss(c, [tx("a", 1050), tx("b", 1020, date(2026, 10, 4))]).key == "b"
    # 差同 → 天數差
    assert hints.near_miss(c, [tx("a", 1020, date(2026, 10, 4)), tx("b", 980)]).key == "b"
    # 都同 → key 最小
    assert hints.near_miss(c, [tx("z", 1020), tx("m", 980)]).key == "m"


def test_repeat_months_算月份不算筆數():
    allc = [ch(690, date(2026, 8, 5)), ch(690, date(2026, 8, 20), n=1), ch(690, date(2026, 9, 5), n=2),
            ch(690, date(2026, 10, 3), n=3), ch(690, date(2026, 10, 3), card="5678", n=4), ch(700, date(2026, 7, 1), n=5)]
    assert hints.repeat_months(ch(690, date(2026, 10, 3)), allc) == 3
    assert hints.repeat_months(ch(999), [ch(999)]) == 1


def test_classify_優先序():
    near = tx("a", 1)
    assert hints.classify(ch(50, region="US"), near, 5) == "near"
    assert hints.classify(ch(50, region="US"), None, 3) == "subscription"
    assert hints.classify(ch(50, region="US"), None, 2) == "overseas"
    assert hints.classify(ch(50, region="TW"), None, 1) == "small"
    assert hints.classify(ch(50, region=None), None, 1) == "small"
    assert hints.classify(ch(100), None, 1) == "small"
    assert hints.classify(ch(101), None, 1) == "other"


def test_hint_text兩種格式():
    near = TxHint("a", date(2026, 10, 2), 1234, "某店")
    assert hints.hint_text(ch(1200), near, 1) == "≈ 帳上 10/02 某店 $1,234（差 $34）"
    nolabel = TxHint("a", date(2026, 10, 2), 1190, None)
    assert hints.hint_text(ch(1200), nolabel, 1) == "≈ 帳上 10/02 （無品名） $1,190（差 $10）"
    assert hints.hint_text(ch(690), None, 4) == "同卡同金額 4 個月都有"
    assert hints.hint_text(ch(690), None, 2) is None


def test_arrange_分組順序_空組不出現_組內排序():
    items = [(5, ch(500, date(2026, 10, 3))), (2, ch(900, date(2026, 10, 1), region="US")),
             (9, ch(60, date(2026, 10, 2))), (1, ch(500, date(2026, 10, 3))), (7, ch(1000, date(2026, 10, 3)))]
    txs = [tx("t", 1050, date(2026, 10, 3), "某店")]
    out = hints.arrange(items, txs, [c for _, c in items])
    assert [g for g, _ in out] == ["near", "overseas", "small", "other"]
    assert [i for i, _, _ in out[0][1]] == [7]
    assert out[0][1][0][2].startswith("≈ 帳上 10/03 某店")
    assert [i for i, _, _ in out[3][1]] == [1, 5]
    assert out[3][1][0][2] is None


def test_arrange_組內先比日期_id大但日期早的排前面():
    items = [(1, ch(500, date(2026, 10, 5))), (9, ch(600, date(2026, 10, 2)))]
    out = hints.arrange(items, [], [c for _, c in items])
    assert [i for i, _, _ in out[0][1]] == [9, 1]
