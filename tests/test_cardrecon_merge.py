from datetime import date, timedelta

from cardrecon.match import merge_updates, pair_merges
from cardrecon.types import Charge

D = date(2026, 9, 5)


def line(amount, d=D, t=None, merchant=None, card="1234", merchant_type=None):
    return Charge(source="ctbc_line", card_last4=card, charge_date=d, amount=amount, line_no=0,
                  charge_time=t, merchant=merchant, merchant_type=merchant_type)


def stmt(amount, d=D, n=0, merchant=None, post=None, region=None, card="1234"):
    return Charge(source="ctbc_statement", card_last4=card, charge_date=d, amount=amount, line_no=n,
                  post_date=post, region=region, merchant=merchant)


def test_同卡同額同日_一對一():
    inc = [(0, stmt(55, d=D)), (1, stmt(55, d=D))]
    cand = [(10, line(55, d=D, t="08:00")), (11, line(55, d=D, t="12:00"))]
    assert pair_merges(inc, cand) == {0: 10, 1: 11}


def test_同卡同額同日_依時間順序配_不看傳入順序():
    inc = [(1, line(55, t="12:00")), (0, line(55, t="08:00"))]
    cand = [(11, stmt(55, n=1)), (10, stmt(55, n=0))]
    assert pair_merges(inc, cand) == {0: 10, 1: 11}


def test_先配同日再配差一天():
    # 差一天的 incoming 排在前面，但同日那筆要先拿走唯一的 candidate
    inc = [(0, stmt(300, d=D - timedelta(days=1))), (1, stmt(300, d=D))]
    cand = [(10, line(300, d=D, t="09:00"))]
    assert pair_merges(inc, cand) == {1: 10}


def test_同日配完_剩下的再配差一天():
    inc = [(0, stmt(300, d=D - timedelta(days=1))), (1, stmt(300, d=D))]
    cand = [(10, line(300, d=D, t="09:00")), (11, line(300, d=D - timedelta(days=2), t="09:00"))]
    assert pair_merges(inc, cand) == {1: 10, 0: 11}


def test_金額或卡號不同_不配():
    assert pair_merges([(0, stmt(500))], [(10, line(501))]) == {}
    assert pair_merges([(0, stmt(500, card="1234"))], [(10, line(500, card="5678"))]) == {}


def test_差兩天_不配():
    assert pair_merges([(0, stmt(500, d=D + timedelta(days=2)))], [(10, line(500, d=D))]) == {}
    assert pair_merges([(0, stmt(500, d=D + timedelta(days=1)))], [(10, line(500, d=D))]) == {0: 10}


def test_slack_days_0_只配同日():
    assert pair_merges([(0, stmt(500, d=D + timedelta(days=1)))], [(10, line(500, d=D))], slack_days=0) == {}


def test_merge_updates_LINE優先店名時間_帳單補入帳日與地區():
    u = merge_updates(line(500, merchant="A店", t="12:30"), stmt(500, merchant="A店OCR", post=date(2026, 9, 7), region="TW"))
    assert u == {"post_date": date(2026, 9, 7), "region": "TW"}
    u2 = merge_updates(stmt(500, merchant="A店OCR"), line(500, merchant="A店", t="12:30"))
    assert u2 == {"merchant": "A店", "charge_time": "12:30"}


def test_merge_updates_LINE只有商店類型_店名用帳單的():
    u = merge_updates(line(359, t="10:00", merchant_type="居家/修繕/3C家電"), stmt(359, merchant="SHOP.EXAMPLE"))
    assert u == {"merchant": "SHOP.EXAMPLE"}
    u2 = merge_updates(stmt(359, merchant="SHOP.EXAMPLE"), line(359, t="10:00", merchant_type="居家/修繕/3C家電"))
    assert u2 == {"charge_time": "10:00", "merchant_type": "居家/修繕/3C家電"}
