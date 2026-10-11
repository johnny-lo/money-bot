from datetime import date, datetime

from cardrecon import match
from cardrecon.types import Charge, Receipt, TxGroup

D = date(2026, 9, 10)


def ch(amount, d=D, merchant=None, n=0):
    return Charge(source="sinopac_daily", card_last4="1234", charge_date=d, amount=amount, line_no=n, merchant=merchant)


def g(key, amount, d):
    return TxGroup(key=key, tx_date=d, amount=amount)


def test_同日同額_配到():
    assert match.match([(1, ch(100))], [g("A", 100, D)]) == {1: "A"}


def test_位移順序_同日優先於隔天():
    groups = [g("next", 100, date(2026, 9, 11)), g("same", 100, D)]
    assert match.match([(1, ch(100))], groups) == {1: "same"}


def test_負一天與加三天都配得到_加四天不配():
    assert match.match([(1, ch(100))], [g("A", 100, date(2026, 9, 9))]) == {1: "A"}
    assert match.match([(1, ch(100))], [g("A", 100, date(2026, 9, 13))]) == {1: "A"}
    assert match.match([(1, ch(100))], [g("A", 100, date(2026, 9, 14))]) == {}
    assert match.match([(1, ch(100))], [g("A", 100, date(2026, 9, 8))]) == {}


def test_金額不同_不配():
    assert match.match([(1, ch(100))], [g("A", 101, D)]) == {}


def test_一對一_兩筆同額只吃一個群組():
    got = match.match([(1, ch(100)), (2, ch(100, n=1))], [g("A", 100, D)])
    assert got == {1: "A"}


def test_依刷卡日由舊到新():
    early, late = ch(100, date(2026, 9, 9)), ch(100, date(2026, 9, 11), n=1)
    got = match.match([(2, late), (1, early)], [g("A", 100, date(2026, 9, 10))])
    assert got == {1: "A"}


def test_enrich_只補沒店名的_同額0到1天_一對一():
    charges = [(1, ch(110)), (2, ch(110, n=1)), (3, ch(110, merchant="已有", n=2))]
    receipts = [Receipt(paid_date=D, amount=110, merchant="停車費")]
    assert match.enrich(charges, receipts) == {1: "停車費"}


def test_enrich_差兩天不補():
    assert match.enrich([(1, ch(110))], [Receipt(paid_date=date(2026, 9, 12), amount=110, merchant="x")]) == {}


def test_group_transactions_發票加總含折扣_手記帳各自一組():
    rows = [
        (1, "AB123", datetime(2026, 9, 10, 12, 0), 288),
        (2, "AB123", datetime(2026, 9, 10, 12, 0), -40),
        (3, None, datetime(2026, 9, 11, 8, 0), 90),
    ]
    got = sorted(match.group_transactions(rows), key=lambda x: x.key)
    assert got == [TxGroup("AB123", D, 248), TxGroup("id3", date(2026, 9, 11), 90)]
