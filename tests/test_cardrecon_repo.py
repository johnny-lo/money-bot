from datetime import date, datetime
from types import SimpleNamespace

from cardrecon import repo
from cardrecon.types import Charge, TxGroup

D = date(2026, 9, 10)


def ch(amount=100, n=0, **kw):
    return Charge(source="sinopac_daily", card_last4="1234", charge_date=D, amount=amount, line_no=n, **kw)


class FakeQuery:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows


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
    f = repo.transaction_fields(ch(420, region="US", charge_time="21:05"))
    assert f == {"item": "信用卡消費（US）", "price": 420, "source": "信用卡",
                 "created_at": datetime(2026, 9, 10, 21, 5), "invoice_no": None, "seller": None,
                 "category": None}
    f2 = repo.transaction_fields(ch(450, merchant="ACME", region="US"))
    assert f2["item"] == "ACME" and f2["created_at"] == datetime(2026, 9, 10, 12, 0)


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
