from datetime import date

from cardrecon import hints
from cardrecon.types import Charge

D = date(2026, 10, 3)


def ch(amount, d=D, card="1234", region="TW", n=0):
    return Charge(source="sinopac_daily", card_last4=card, charge_date=d, amount=amount, line_no=n, region=region)


def test_GROUPS順序():
    assert [k for k, _ in hints.GROUPS] == ["subscription", "overseas", "small", "other"]
    assert "near" not in dict(hints.GROUPS)


def test_repeat_months_算月份不算筆數():
    allc = [ch(690, date(2026, 8, 5)), ch(690, date(2026, 8, 20), n=1), ch(690, date(2026, 9, 5), n=2),
            ch(690, date(2026, 10, 3), n=3), ch(690, date(2026, 10, 3), card="5678", n=4), ch(700, date(2026, 7, 1), n=5)]
    assert hints.repeat_months(ch(690, date(2026, 10, 3)), allc) == 3
    assert hints.repeat_months(ch(999), [ch(999)]) == 1


def test_classify_優先序():
    assert hints.classify(ch(50, region="US"), 5) == "subscription"
    assert hints.classify(ch(50, region="US"), 3) == "subscription"
    assert hints.classify(ch(50, region="US"), 2) == "overseas"
    assert hints.classify(ch(50, region="TW"), 1) == "small"
    assert hints.classify(ch(50, region=None), 1) == "small"
    assert hints.classify(ch(100), 1) == "small"
    assert hints.classify(ch(101), 1) == "other"


def test_hint_text只有同卡同金額():
    assert hints.hint_text(ch(690), 4) == "同卡同金額 4 個月都有"
    assert hints.hint_text(ch(690), 3) == "同卡同金額 3 個月都有"
    assert hints.hint_text(ch(690), 2) is None
    assert hints.hint_text(ch(1200), 1) is None


def test_arrange_分組順序_空組不出現_組內排序():
    items = [(5, ch(500, date(2026, 10, 3))), (2, ch(900, date(2026, 10, 1), region="US")),
             (9, ch(60, date(2026, 10, 2))), (1, ch(500, date(2026, 10, 3))), (7, ch(1000, date(2026, 10, 3)))]
    out = hints.arrange(items, [c for _, c in items])
    assert [g for g, _ in out] == ["overseas", "small", "other"]
    assert [i for i, _, _ in out[2][1]] == [1, 5, 7]
    assert all(h is None for _, grp in out for _, _, h in grp)


def test_arrange_金額接近或時間接近的刷卡_照原規則分組_沒有近似線索():
    # 帳上金額不同的紀錄不是線索：分組只看重複月份、地區、金額
    sub = [(10 + m, ch(1050, date(2026, m, 3), n=m)) for m in (8, 9, 10)]
    items = [(1, ch(1000)), (2, ch(900, region="US")), (3, ch(55)),
             (4, Charge(source="sinopac_daily", card_last4="1234", charge_date=D, amount=500, line_no=4,
                        charge_time="12:00", region="TW"))] + sub
    out = hints.arrange(items, [c for _, c in items])
    assert [g for g, _ in out] == ["subscription", "overseas", "small", "other"]
    assert [i for i, _, _ in out[0][1]] == [18, 19, 20]
    assert out[0][1][0][2] == "同卡同金額 3 個月都有"
    assert [i for i, _, _ in out[3][1]] == [1, 4]
    assert not any(h and "≈" in h for _, grp in out for _, _, h in grp)


def test_arrange_組內先比日期_id大但日期早的排前面():
    items = [(1, ch(500, date(2026, 10, 5))), (9, ch(600, date(2026, 10, 2)))]
    out = hints.arrange(items, [c for _, c in items])
    assert [i for i, _, _ in out[0][1]] == [9, 1]
