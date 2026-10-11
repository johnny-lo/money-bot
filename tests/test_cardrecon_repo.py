from datetime import date, datetime
from types import SimpleNamespace

from cardrecon import repo
from cardrecon.types import Charge, TxGroup, TxHint

D = date(2026, 9, 10)


def ch(amount=100, n=0, **kw):
    return Charge(source="sinopac_daily", card_last4="1234", charge_date=D, amount=amount, line_no=n, **kw)


class FakeQuery:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def distinct(self, *a): return self


class FakeSession:
    def __init__(self, rows=()):
        self.rows, self.added, self.commits, self._next = list(rows), [], 0, 900
    def query(self, *a, **k): return FakeQuery(self.rows)
    def add(self, o): self.added.append(o)
    def flush(self):
        for o in self.added:
            if getattr(o, "id", None) is None:
                o.id = self._next; self._next += 1
    def commit(self): self.commits += 1
    def rollback(self): pass


def test_upsert_已存在的行不重寫_也不蓋狀態():
    db = FakeSession(rows=[(0,)])                       # line_no 0 已存在
    n = repo.upsert_charges(db, "<m1>", [ch(n=0), ch(200, n=1)])
    assert n == 1 and len(db.added) == 1
    row = db.added[0]
    assert (row.message_id, row.line_no, row.amount, row.status) == ("<m1>", 1, 200, "unmatched")
    assert db.commits == 1


def test_transaction_fields_補記寫入契約():
    f = repo.transaction_fields(ch(450, region="US", charge_time="22:41"))
    assert f == {"item": "信用卡消費（US）", "price": 450, "source": "信用卡",
                 "created_at": datetime(2026, 9, 10, 22, 41), "invoice_no": None, "seller": None,
                 "category": None}
    f2 = repo.transaction_fields(ch(690, merchant="ACME *STREAMING", region="US"))
    assert f2["item"] == "ACME *STREAMING" and f2["created_at"] == datetime(2026, 9, 10, 12, 0)


def _row(i, amount, status="unmatched", **kw):
    base = dict(id=i, source="sinopac_daily", card_last4="1234", charge_date=D, amount=amount, line_no=i,
                charge_time=None, post_date=None, region="TW", merchant=None, pay_method=None,
                status=status, matched_key=None, batch="2026-09-20-1")
    base.update(kw)
    return SimpleNamespace(**base)


def test_record_先重比_配到的不補記_其餘補記_同一次commit(monkeypatch):
    rows = [_row(1, 100), _row(2, 250), _row(3, 70, status="ignored")]
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: rows)
    monkeypatch.setattr(repo, "load_groups", lambda db, since: [TxGroup("INV9", D, 100)])
    monkeypatch.setattr(repo, "used_group_keys", lambda db: set())
    db = FakeSession()
    res = repo.record(db, "2026-09-20-1")
    assert (res.recorded, res.total, res.matched) == (1, 250, 1)
    assert (rows[0].status, rows[0].matched_key) == ("matched", "INV9")
    assert rows[1].status == "recorded" and rows[1].matched_key == f"id{db.added[0].id}"
    assert rows[2].status == "ignored"
    assert db.added[0].source == "信用卡" and db.added[0].price == 250
    assert db.commits == 1


def test_record_按第二次_零筆(monkeypatch):
    rows = [_row(1, 100, status="recorded")]
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: rows)
    db = FakeSession()
    res = repo.record(db, "b")
    assert (res.recorded, res.total, res.matched) == (0, 0, 0) and db.added == []


def test_record_已被佔用的群組不能再配(monkeypatch):
    rows = [_row(1, 100)]
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: rows)
    monkeypatch.setattr(repo, "load_groups", lambda db, since: [TxGroup("INV9", D, 100)])
    monkeypatch.setattr(repo, "used_group_keys", lambda db: {"INV9"})
    res = repo.record(FakeSession(), "b")
    assert res.recorded == 1 and rows[0].status == "recorded"


def test_ignore_只動該批的未配對(monkeypatch):
    rows = [_row(1, 100), _row(2, 200, status="recorded"), _row(3, 300)]
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: rows)
    db = FakeSession()
    assert repo.ignore(db, "b", [1, 2]) == 1
    assert [r.status for r in rows] == ["ignored", "recorded", "unmatched"]
    assert db.commits == 1


def test_has_source_有無資料():
    assert repo.has_source(FakeSession([(1,)]), "ctbc_statement") is True
    assert repo.has_source(FakeSession(), "ctbc_statement") is False


def test_max_page_取同日最大頁碼():
    rows = [("2026-10-18-1",), ("2026-10-18-2",), ("2026-10-18-10",), ("2026-10-11-7",), ("2026-10-18-x",), (None,)]
    assert repo.max_page(FakeSession(rows), "2026-10-18") == 10
    assert repo.max_page(FakeSession(), "2026-10-18") == 0


def test_load_hints_同發票合併_標籤取賣家否則第一個品名_排除已佔用(monkeypatch):
    t = datetime(2026, 9, 10, 12, 0)
    rows = [(1, "INV1", t, 80, "豆漿", "某早餐店"), (2, "INV1", t, 20, "蛋餅", "某早餐店"),
            (3, None, t, 300, "手記午餐", None), (4, "INV2", t, 50, "咖啡", None), (5, "INV3", t, 70, "茶", None),
            (6, "INV3", t, 30, "糖", None),
            (7, "INV4", t, 40, "麵", None), (8, "INV4", t, 60, "飯", "某小館")]
    monkeypatch.setattr(repo, "used_group_keys", lambda db: {"INV2"})
    got = repo.load_hints(FakeSession(rows), D)
    assert sorted(got, key=lambda h: h.key) == [TxHint("INV1", D, 100, "某早餐店"), TxHint("INV3", D, 100, "茶"), TxHint("INV4", D, 100, "某小館"),
                                                TxHint("id3", D, 300, "手記午餐")]


def test_all_charges轉成Charge():
    got = repo.all_charges(FakeSession([_row(1, 100), _row(2, 250)]))
    assert [c.amount for c in got] == [100, 250] and all(isinstance(c, Charge) for c in got)


def test_unlist_只清未配對且有批次的_其餘不動_一次commit():
    rows = [_row(1, 100), _row(2, 200, status="ignored"), _row(3, 300, status="recorded"),
            _row(4, 400, status="matched"), _row(5, 500, batch=None), _row(6, 600)]
    db = FakeSession(rows)
    assert repo.unlist(db) == 2
    assert [r.batch for r in rows] == [None, "2026-09-20-1", "2026-09-20-1", "2026-09-20-1", None, None]
    assert [r.status for r in rows] == ["unmatched", "ignored", "recorded", "matched", "unmatched", "unmatched"]
    assert db.commits == 1


def test_batch_view_重算線索_保留各列狀態_回傳多數組別(monkeypatch):
    rows = [_row(1, 1000, region="TW"), _row(2, 1000, status="ignored", region="TW", card_last4="5678"),
            _row(3, 60, region="TW")]
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: rows)
    monkeypatch.setattr(repo, "load_hints", lambda db, since: [TxHint("t", D, 1040, "某店")])
    monkeypatch.setattr(repo, "all_charges", lambda db: [repo._to_charge(r) for r in rows])
    gk, items = repo.batch_view(FakeSession(), "b")
    assert gk == "near"
    assert {(i, s) for i, _, s, _ in items} == {(1, "unmatched"), (2, "ignored"), (3, "unmatched")}
    by = {i: h for i, _, _, h in items}
    assert by[1].startswith("≈ 帳上 09/10 某店") and by[3] is None
