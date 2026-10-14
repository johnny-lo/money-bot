"""刷卡有時間（永豐 HH:MM）時用發票開立時間對帳；分期顯示期數。"""
from datetime import date, datetime, time
from types import SimpleNamespace

from cardrecon import config, match, repo
from cardrecon.types import Charge, TxGroup

D = date(2026, 9, 10)
D1 = date(2026, 9, 11)


def ch(amount, d=D, t=None, n=0, src="sinopac_daily", merchant=None):
    return Charge(source=src, card_last4="1234", charge_date=d, amount=amount, line_no=n, charge_time=t,
                  merchant=merchant)


def g(key, amount, d=D, t=None):
    return TxGroup(key=key, tx_date=d, amount=amount, tx_time=t)


def test_時間窗口是設定常數():
    assert config.TIME_WINDOW_MIN == 10


# ── AC5 群組帶時間 ───────────────────────────────────────

def test_group_transactions_只有發票且非0點才有時間():
    rows = [(1, "AA00000001", datetime(2026, 9, 10, 12, 38), 30),
            (2, "AA00000001", datetime(2026, 9, 10, 12, 38), 13),
            (3, "BB00000002", datetime(2026, 9, 10, 0, 0), 50),       # 舊發票：00:00＝沒有時間
            (4, None, datetime(2026, 9, 10, 12, 40), 90)]             # 手記帳：記帳時間不是消費時間
    got = {x.key: x for x in match.group_transactions(rows)}
    assert (got["AA00000001"].amount, got["AA00000001"].tx_time) == (43, time(12, 38))
    assert got["BB00000002"].tx_time is None
    assert got["id4"].tx_time is None


# ── AC5 時間配對 ─────────────────────────────────────────

def test_時間配對優先於日期配對():
    # 同金額兩張：一張同日但差好幾小時、一張隔天但只差 3 分鐘（跨午夜）
    groups = [g("same", 100, D, time(15, 0)), g("near", 100, D1, time(0, 1))]
    assert match.match([(1, ch(100, t="23:58"))], groups) == {1: "near"}


def test_時間配對_跨午夜往前一天():
    groups = [g("today", 100, D1), g("prev", 100, D, time(23, 58))]
    assert match.match([(1, ch(100, D1, "00:02"))], groups) == {1: "prev"}


def test_時間配對_多張取時間差最小_窗口邊界():
    groups = [g("a", 100, D, time(12, 9)), g("b", 100, D, time(11, 58)), g("c", 100, D, time(12, 10))]
    assert match.match([(1, ch(100, t="12:00"))], groups) == {1: "b"}
    assert match.match([(1, ch(100, D1, "12:00"))], [g("x", 100, D1, time(12, 10))]) == {1: "x"}
    # 差 11 分鐘：時間配不到，退回日期配對（同日照樣配到）
    assert match.match([(1, ch(100, t="12:00"))], [g("x", 100, D, time(12, 11))]) == {1: "x"}


def test_時間差超過窗口_走原本日期差_不搶時間更近的():
    groups = [g("far", 100, D, time(8, 0)), g("close", 100, D1, time(0, 5))]
    assert match.match([(1, ch(100, t="23:57"))], groups) == {1: "close"}
    assert match.match([(1, ch(100, t="20:00"))], groups) == {1: "far"}      # 都不在窗口內 → 同日優先


def test_手記帳不參與時間配對():
    rows = [(5, None, datetime(2026, 9, 11, 0, 1), 100), (6, "INV", datetime(2026, 9, 10, 15, 0), 100)]
    groups = match.group_transactions(rows)
    assert match.match([(1, ch(100, t="23:58"))], groups) == {1: "INV"}       # 手記帳 3 分鐘也不算


def test_0點視為沒有時間():
    rows = [(5, "MID", datetime(2026, 9, 11, 0, 0), 100), (6, "SAME", datetime(2026, 9, 10, 12, 0), 100)]
    groups = match.group_transactions(rows)
    assert match.match([(1, ch(100, t="23:55"))], groups) == {1: "SAME"}


def test_沒有時間的刷卡行為不變():
    groups = [g("next", 100, D1, time(0, 1)), g("same", 100, D, time(15, 0))]
    assert match.match([(1, ch(100, src="ctbc_statement"))], groups) == {1: "same"}


def test_時間配對先於其他刷卡的日期配對():
    # 刷卡 1（較早、無時間）若先走日期差會吃掉 INV；INV 跟刷卡 2 只差 2 分鐘，應該給刷卡 2
    groups = [g("INV", 100, D1, time(9, 2)), g("OTHER", 100, date(2026, 9, 12))]
    got = match.match([(1, ch(100, D, src="ctbc_statement")), (2, ch(100, D1, "09:00", n=1))], groups)
    assert got == {2: "INV", 1: "OTHER"}


# ── AC6 多張發票合計 ─────────────────────────────────────

def test_多張發票合計剛好等於刷卡_一起配():
    groups = [g("B", 200, D, time(12, 5)), g("A", 100, D, time(11, 52)), g("Z", 50, D, time(12, 30))]
    got = match.match([(1, ch(300, t="12:00"))], groups)
    assert got == {1: "A+B"}
    assert set(got[1].split(config.KEY_SEP)) == {"A", "B"}


def test_合計不相等不配():
    groups = [g("A", 100, D, time(12, 1)), g("B", 150, D, time(12, 2))]
    assert match.match([(1, ch(300, t="12:00"))], groups) == {}


def test_合計最多四張():
    four = [g(f"K{i}", 75, D, time(12, i)) for i in range(4)]
    assert match.match([(1, ch(300, t="12:00"))], four) == {1: "K0+K1+K2+K3"}
    five = [g(f"K{i}", 60, D, time(12, i)) for i in range(5)]
    assert match.match([(1, ch(300, t="12:00"))], five) == {}


def test_合計不重用已配走的_也不用窗口外或沒時間的():
    groups = [g("A", 100, D, time(12, 1)), g("B", 200, D, time(12, 4))]
    got = match.match([(1, ch(100, t="12:00")), (2, ch(300, t="12:03", n=1))], groups)
    assert got == {1: "A"}                                   # A 已被刷卡 1 單張配走 → 刷卡 2 湊不齊
    assert match.match([(1, ch(300, t="12:00"))], [g("A", 100, D, time(12, 11)), g("B", 200, D, time(12, 1))]) == {}
    assert match.match([(1, ch(300, t="12:00"))], [g("id1", 100), g("B", 200, D, time(12, 1))]) == {}


def test_合計_沒有時間的刷卡不做():
    groups = [g("A", 100, D, time(12, 1)), g("B", 200, D, time(12, 4))]
    assert match.match([(1, ch(300, src="ctbc_statement"))], groups) == {}


class _Q:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows


class _S:
    def __init__(self, rows=()): self.rows = list(rows)
    def query(self, *a, **k): return _Q(self.rows)


def test_repo已用鍵拆開多鍵():
    db = _S([("A+B",), ("id3",), ("C",)])
    assert repo.used_group_keys(db) == {"A", "B", "id3", "C"}


# ── 時間接近、金額不同的發票不是線索 ─────────────────────

def test_batch_view_永豐刷卡_時間接近金額不同的發票_不成線索(monkeypatch):
    row = SimpleNamespace(id=1, source="sinopac_daily", card_last4="1234", charge_date=D, amount=500, line_no=0,
                          charge_time="12:00", post_date=None, region="TW", merchant=None, pay_method=None,
                          status="unmatched", matched_key=None, batch="b")
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: [row])
    monkeypatch.setattr(repo, "brand_map", lambda db: {})
    monkeypatch.setattr(repo, "all_charges", lambda db: [])
    gk, items = repo.batch_view(None, "b")
    assert gk == "other" and items[0][3] is None


# ── AC9 分期 ─────────────────────────────────────────────

def test_分期_有品牌對照():
    brands = {"富邦EC分期03-03": "富邦EC", "某某百貨分期01－12": "某某百貨"}
    assert repo.display_name("富邦EC分期03-03", brands) == "富邦EC（分期 3/3）"
    assert repo.display_name("某某百貨分期01－12", brands) == "某某百貨（分期 1/12）"       # 全形連字號


def test_分期_沒有品牌對照用原名去掉分期字樣():
    assert repo.display_name("某某電器 分期 02 - 06", {}) == "某某電器（分期 2/6）"
    assert repo.display_name("某某電器分期10－10", {}) == "某某電器（分期 10/10）"


def test_分期_品牌本身還留著分期字樣也拿掉():
    assert repo.display_name("某某電器分期02-06", {"某某電器分期02-06": "某某電器分期02-06"}) == "某某電器（分期 2/6）"


def test_不含分期的店名不變():
    assert repo.display_name("ACME *STREAMING", {}) == "ACME *STREAMING"
    assert repo.display_name("某某商店股份有限公司", {"某某商店股份有限公司": "某某"}) == "某某"
    assert repo.display_name(None, {}) is None
    assert repo.display_name("", {}) == ""


def test_清單與補記用同一個顯示名稱():
    brands = {"富邦EC分期03-03": "富邦EC"}
    c = ch(1000, merchant="富邦EC分期03-03")
    assert repo.branded(c, brands).merchant == "富邦EC（分期 3/3）"
    assert repo.transaction_fields(c, brands)["item"] == "富邦EC（分期 3/3）"
    assert repo.transaction_fields(ch(1000, merchant="某某電器分期02-06"))["item"] == "某某電器（分期 2/6）"
