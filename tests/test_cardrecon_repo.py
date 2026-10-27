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
                charge_time=None, post_date=None, region="TW", merchant=None, pay_method=None, merchant_type=None,
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
    # 這批在帳上有金額相近的紀錄也一樣：沒有 near 組，依重複月份、地區、金額回報多數組別
    rows = [_row(1, 1000, region="TW"), _row(2, 1000, status="ignored", region="TW", card_last4="5678"),
            _row(3, 60, region="TW")]
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: rows)
    monkeypatch.setattr(repo, "brand_map", lambda db: {})
    monkeypatch.setattr(repo, "all_charges", lambda db: [repo._to_charge(r) for r in rows])
    gk, items = repo.batch_view(FakeSession(), "b")
    assert gk == "other"
    assert {(i, s) for i, _, s, _ in items} == {(1, "unmatched"), (2, "ignored"), (3, "unmatched")}
    assert all(h is None for _, _, _, h in items)


def test_batch_view_同卡同金額多月_回報訂閱組(monkeypatch):
    rows = [_row(1, 690, region="TW"), _row(2, 690, region="TW")]
    past = [repo._to_charge(r) for r in rows] + [
        Charge(source="sinopac_daily", card_last4="1234", charge_date=date(2026, m, 10), amount=690, line_no=m)
        for m in (7, 8)]
    monkeypatch.setattr(repo, "_batch_rows", lambda db, b: rows)
    monkeypatch.setattr(repo, "brand_map", lambda db: {})
    monkeypatch.setattr(repo, "all_charges", lambda db: past)
    gk, items = repo.batch_view(FakeSession(), "b")
    assert gk == "subscription"
    assert [h for _, _, _, h in items] == ["同卡同金額 3 個月都有"] * 2


def stmt(amount, n=0, d=D, **kw):
    return Charge(source="ctbc_statement", card_last4="1234", charge_date=d, amount=amount, line_no=n, **kw)


def test_upsert_帳單行配到LINE列_存成merged並補欄位(monkeypatch):
    cand = _row(7, 500, status="matched", source="ctbc_line", line_no=0, charge_time="12:30", merchant="A店",
                region=None, matched_key="INV1", batch="2026-09-13-1", merged_into=None)
    calls = []

    def cands(db, source, charges):
        calls.append((source, list(charges)))
        return [(7, repo._to_charge(cand))]
    monkeypatch.setattr(repo, "_merge_candidates", cands)
    monkeypatch.setattr(repo, "_by_ids", lambda db, ids: [cand] if 7 in set(ids) else [])
    db = FakeSession()
    incoming = [stmt(500, 0, post_date=date(2026, 9, 12), region="TW", merchant="A店OCR"), stmt(300, 1)]
    n = repo.upsert_charges(db, "<ctbc1>", incoming)
    assert n == 2 and calls == [("ctbc_line", incoming)]
    merged, plain = db.added
    assert (merged.line_no, merged.status, merged.merged_into, merged.message_id) == (0, "merged", 7, "<ctbc1>")
    assert (plain.line_no, plain.status, plain.merged_into) == (1, "unmatched", None)
    assert (cand.post_date, cand.region, cand.merchant, cand.charge_time) == (date(2026, 9, 12), "TW", "A店", "12:30")
    assert (cand.status, cand.matched_key, cand.batch) == ("matched", "INV1", "2026-09-13-1")
    assert db.commits == 1


def test_upsert_LINE列配到帳單列_帳單列改用LINE的店名與時間(monkeypatch):
    cand = _row(8, 500, status="ignored", source="ctbc_statement", line_no=3, merchant="A店OCR",
                post_date=date(2026, 9, 12), batch="2026-09-20-2", merged_into=None)
    monkeypatch.setattr(repo, "_merge_candidates", lambda db, source, charges: [(8, repo._to_charge(cand))])
    monkeypatch.setattr(repo, "_by_ids", lambda db, ids: [cand])
    db = FakeSession()
    c = Charge(source="ctbc_line", card_last4="1234", charge_date=D, amount=500, line_no=0,
               charge_time="12:30", merchant="A店")
    assert repo.upsert_charges(db, "line:m1", [c]) == 1
    assert (db.added[0].status, db.added[0].merged_into) == ("merged", 8)
    assert (cand.merchant, cand.charge_time, cand.post_date) == ("A店", "12:30", date(2026, 9, 12))
    assert (cand.status, cand.matched_key, cand.batch) == ("ignored", None, "2026-09-20-2")
    assert db.commits == 1


def test_upsert_同一封帳單第二次_不重插也不再合併(monkeypatch):
    def boom(*a, **k): raise AssertionError("已存在的列不該再找合併對象")
    monkeypatch.setattr(repo, "_merge_candidates", boom)
    monkeypatch.setattr(repo, "_by_ids", boom)
    db = FakeSession(rows=[(0,), (1,)])
    assert repo.upsert_charges(db, "<ctbc1>", [stmt(500, 0), stmt(300, 1)]) == 0
    assert db.added == [] and db.commits == 1


def test_upsert_永豐不找合併對象_照舊unmatched(monkeypatch):
    def boom(*a, **k): raise AssertionError("永豐不參與合併")
    monkeypatch.setattr(repo, "_merge_candidates", boom)
    db = FakeSession()
    assert repo.upsert_charges(db, "<s1>", [ch(100, 0)]) == 1
    assert (db.added[0].status, db.added[0].merged_into) == ("unmatched", None)


def test_upsert_沒配到_照舊unmatched(monkeypatch):
    monkeypatch.setattr(repo, "_merge_candidates", lambda db, source, charges: [])
    monkeypatch.setattr(repo, "_by_ids", lambda db, ids: [])
    db = FakeSession()
    assert repo.upsert_charges(db, "<ctbc1>", [stmt(500, 0)]) == 1
    assert (db.added[0].status, db.added[0].merged_into) == ("unmatched", None)


class RecordingQuery(FakeQuery):
    def __init__(self, rows, log, counts=None):
        super().__init__(rows)
        self.log, self.counts = log, counts
    def filter(self, *a, **k):
        self.log.extend(a)
        return self
    def count(self): return self.counts.pop(0)


class RecordingSession(FakeSession):
    def __init__(self, rows=(), counts=None):
        super().__init__(rows)
        self.queries, self.counts = [], counts
    def query(self, *a, **k):
        log = []
        self.queries.append(log)
        return RecordingQuery(self.rows, log, self.counts)


def _conds(exprs):
    """把 filter 收到的 `欄位 op 值` 運算式攤成 (欄位, 運算子名, 值)。"""
    return {(e.left.key, e.operator.__name__, e.right.value) for e in exprs}


def test_all_charges_排除merged():
    db = RecordingSession([_row(1, 100)])
    assert [c.amount for c in repo.all_charges(db)] == [100]
    assert ("status", "ne", "merged") in _conds(db.queries[0])


def test_transaction_fields_沒店名用商店類型():
    f = repo.transaction_fields(Charge(source="ctbc_line", card_last4="1234", charge_date=D, amount=359, line_no=0,
                                       charge_time="10:05", merchant_type="居家/修繕/3C家電"))
    assert f["item"] == "信用卡消費（居家/修繕/3C家電）" and f["created_at"] == datetime(2026, 9, 10, 10, 5)
    assert repo.transaction_fields(ch(80))["item"] == "信用卡消費"
    assert repo.transaction_fields(ch(80, region="TW", merchant_type="餐飲"))["item"] == "信用卡消費（餐飲）"
    assert repo.transaction_fields(ch(80, merchant="某店", merchant_type="餐飲"))["item"] == "某店"


def test_set_merchant_by_line_補到被指的列_已有店名的不動(monkeypatch):
    rows = [_row(1, 500, source="ctbc_statement", line_no=0, status="merged", merged_into=7),
            _row(2, 300, source="ctbc_statement", line_no=1, status="merged", merged_into=8),
            _row(3, 200, source="ctbc_statement", line_no=2, merged_into=None)]
    target = {7: _row(7, 500, source="ctbc_line", merchant=None), 8: _row(8, 300, source="ctbc_line", merchant="B店")}
    monkeypatch.setattr(repo, "_by_ids", lambda db, ids: [target[i] for i in ids if i in target])
    db = FakeSession(rows)
    assert repo.set_merchant_by_line(db, "<ctbc1>", {0: "A店OCR", 1: "B店OCR", 2: "C店OCR"}) == 3
    assert [r.merchant for r in rows] == ["A店OCR", "B店OCR", "C店OCR"]
    assert (target[7].merchant, target[8].merchant) == ("A店OCR", "B店")
    assert db.commits == 1


def test_weekly_line_stats_本週LINE筆數與合併筆數():
    since = date(2026, 10, 11)
    db = RecordingSession(counts=[4, 2])
    assert repo.weekly_line_stats(db, since) == (4, 2)
    assert {("source", "eq", "ctbc_line"), ("charge_date", "ge", since)} <= _conds(db.queries[0])
    assert {("status", "eq", "merged"), ("created_at", "ge", datetime(2026, 10, 11))} <= _conds(db.queries[1])
