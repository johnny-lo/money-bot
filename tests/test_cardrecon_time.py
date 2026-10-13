"""刷卡有時間（永豐 HH:MM）時用發票開立時間對帳；時間接近但金額不同的發票當線索；分期顯示期數。"""
from datetime import date, datetime, time
from types import SimpleNamespace

from cardrecon import config, hints, match, repo
from cardrecon.types import Charge, TxGroup, TxHint
from discordbot import cardrecon_ui as ui

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


# ── AC7 時間線索 ─────────────────────────────────────────

def th(key, amount, d=D, t=time(12, 5), label="某某商店"):
    return TxHint(key=key, tx_date=d, amount=amount, label=label, tx_time=t)


def test_時間線索_差10分鐘內_金額不同():
    c = ch(500, t="12:00")
    assert hints.time_near(c, [th("a", 120)]).key == "a"
    assert hints.time_near(c, [th("a", 120, t=time(12, 11))]) is None
    assert hints.time_near(c, [th("a", 500)]) is None                       # 同金額不是線索
    assert hints.time_near(c, [th("a", 0), th("b", -20)]) is None
    assert hints.time_near(ch(500), [th("a", 120)]) is None                 # 刷卡沒時間
    assert hints.time_near(c, [th("a", 120, t=None)]) is None               # 發票沒時間
    assert hints.time_near(ch(500, D1, "00:03"), [th("a", 120, D, time(23, 58))]).key == "a"   # 跨午夜


def test_時間線索_取時間差最小():
    c = ch(500, t="12:00")
    assert hints.time_near(c, [th("a", 120, t=time(12, 6)), th("b", 999, t=time(11, 57))]).key == "b"


def test_時間線索文字_與優先於日期近似():
    c = ch(500, t="12:00")
    manual = TxHint("id2", D, 510, "手記午餐")                               # 原本會被當近似紀錄
    out = hints.arrange([(1, c)], [manual], [c], [th("INV", 1234)])
    assert [k for k, _ in out] == ["near"]
    assert out[0][1][0][2] == "≈ 帳上 12:05 某某商店 $1,234（差 $734）"
    nolabel = hints.arrange([(1, c)], [], [c], [th("INV", 80, label=None)])
    assert nolabel[0][1][0][2] == "≈ 帳上 12:05 （無品名） $80（差 $420）"


def test_沒有時間接近的發票_日期近似邏輯不變():
    c = ch(500, t="12:00")
    manual = TxHint("id2", D, 510, "手記午餐")
    out = hints.arrange([(1, c)], [manual], [c], [th("INV", 1234, t=time(13, 0))])
    assert out[0][1][0][2] == "≈ 帳上 09/10 手記午餐 $510（差 $10）"
    assert hints.arrange([(1, c)], [manual], [c]) == out                     # 不給時間線索也一樣


def test_short_對時間格式照樣截店名():
    long = "很長的店名" * 10
    got = ui._short(f"≈ 帳上 12:05 {long} $1,234（差 $734）")
    assert got == f"≈ 帳上 12:05 {long[:20]}… $1,234（差 $734）"


def test_load_time_hints_只回有時間的發票_標籤賣方優先_排除已配走(monkeypatch):
    t = datetime(2026, 9, 10, 12, 5)
    rows = [(1, "AA00000001", t, 30, "禦飯糰", "某某商店"), (2, "AA00000001", t, 13, "茶葉蛋", "某某商店"),
            (3, "BB00000002", t, 55, "大-冰拿鐵", None),
            (4, "CC00000003", datetime(2026, 9, 10), 20, "紅茶", None),     # 00:00 → 沒時間
            (5, "DD00000004", t, 99, "已配走", None),
            (6, None, t, 70, "手記帳", None)]
    monkeypatch.setattr(repo, "used_group_keys", lambda db: {"DD00000004"})
    got = sorted(repo.load_time_hints(_S(rows), D), key=lambda h: h.key)
    assert got == [TxHint("AA00000001", D, 43, "某某商店", time(12, 5)),
                   TxHint("BB00000002", D, 55, "大-冰拿鐵", time(12, 5))]


def test_batch_view_帶時間線索(monkeypatch):
    row = SimpleNamespace(id=1, source="sinopac_daily", card_last4="1234", charge_date=D, amount=500, line_no=0,
                          charge_time="12:00", post_date=None, region="TW", merchant=None, pay_method=None,
                          status="unmatched", matched_key=None, batch="b")
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: [row])
    monkeypatch.setattr(repo, "brand_map", lambda db: {})
    monkeypatch.setattr(repo, "load_hints", lambda db, since: [])
    monkeypatch.setattr(repo, "load_time_hints", lambda db, since: [th("INV", 120)])
    monkeypatch.setattr(repo, "all_charges", lambda db: [])
    gk, items = repo.batch_view(None, "b")
    assert gk == "near" and items[0][3] == "≈ 帳上 12:05 某某商店 $120（差 $380）"


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
