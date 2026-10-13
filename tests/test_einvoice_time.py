"""發票開立時間：點明細時讀 getCarrierInvoiceData 的 invoiceTime，存進 transactions.created_at。

背景：爬蟲本來就逐張點開明細抓品項，網頁當下打的 API 回傳裡就有 invoiceTime，
created_at 卻只存日期（一律 00:00）——AGENTS.md「抓到了、用過了，就是沒存」那一類。
刷卡比對要用時間對發票，舊發票只能趁政府站還查得到時補。
"""
import asyncio
from datetime import datetime, time

import pytest

import einvoice
from models import Transaction


# ── AC2 純函式 ──────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("12:38:00", time(12, 38)),
    ("12:38", time(12, 38)),
    ("08:05:09", time(8, 5, 9)),
    (" 23:59:59 ", time(23, 59, 59)),
    ("00:00:00", time(0, 0)),
])
def test_parse_invoice_time_可解析(raw, want):
    assert einvoice.parse_invoice_time(raw) == want


@pytest.mark.parametrize("raw", ["", None, "25:00:00", "12:60", "亂碼", "12", "12:38:00:00", 1238])
def test_parse_invoice_time_不合法回None(raw):
    assert einvoice.parse_invoice_time(raw) is None


def test_invoice_datetime_日期加時間_沒時間是當天0點():
    assert einvoice.invoice_datetime("2026-08-29", time(12, 38)) == datetime(2026, 8, 29, 12, 38)
    assert einvoice.invoice_datetime("2026-08-29", None) == datetime(2026, 8, 29, 0, 0)


# ── 明細回應的第二道核對（日期＋金額要跟清單列一致）──────────

_ROW = {"invoice_no": "AA00000001", "date": "2026-06-05", "amount": 1055}


@pytest.mark.parametrize("data,want", [
    ({"invoiceDate": "20260605", "invoiceTime": "12:38:00", "totalAmount": "1055"}, time(12, 38)),
    ({"data": {"invoiceDate": "20260605", "invoiceTime": "12:38:00", "totalAmount": "1,055"}}, time(12, 38)),
    ({"invoiceDate": "20260605", "invoiceTime": "12:38:00", "totalAmount": 1055.0}, time(12, 38)),
])
def test_明細時間_日期金額都對才採用(data, want):
    assert einvoice.checked_detail_time(_ROW, data) == want


@pytest.mark.parametrize("data", [
    None,
    {"invoiceDate": "20260604", "invoiceTime": "12:38:00", "totalAmount": "1055"},   # 別天
    {"invoiceDate": "20260605", "invoiceTime": "12:38:00", "totalAmount": "43"},     # 別的金額
    {"invoiceTime": "12:38:00", "totalAmount": "1055"},                              # 沒日期
    {"invoiceDate": "20260605", "invoiceTime": "12:38:00"},                          # 沒金額
    {"invoiceDate": "20260605", "invoiceTime": "12:38:00", "totalAmount": "亂碼"},
    {"invoiceDate": "20260605", "invoiceTime": "25:00:00", "totalAmount": "1055"},
])
def test_明細時間_對不上或缺欄位一律None(data):
    assert einvoice.checked_detail_time(_ROW, data) is None


# ── AC3 寫入：新增帶時間、已存在只補時間 ─────────────────

class _Query:
    def __init__(self, db):
        self.db, self.no = db, None

    def filter(self, expr):
        self.no = expr.right.value          # Transaction.invoice_no == "<號碼>"
        return self

    def all(self):
        return [r for r in self.db.rows if r.invoice_no == self.no]

    def first(self):
        got = self.all()
        return got[0] if got else None


class _Session:
    """記憶體版 session：rows 是 DB 裡已有的 Transaction，added 是這次新增的。"""
    def __init__(self, rows=()):
        self.rows, self.added, self.commits = list(rows), [], 0

    def query(self, *a):
        return _Query(self)

    def add(self, o):
        self.added.append(o)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _tx(no, created, item="禦飯糰", price=43):
    return Transaction(item=item, price=price, invoice_no=no, source="載具1", seller="某某商店", created_at=created)


def _inv(no="AA00000001", date="2026-08-29", t=time(12, 38), items=None):
    return {"invoice_no": no, "amount": 43, "date": date, "seller": "某某商店", "time": t,
            "items": [{"name": "禦飯糰", "amount": 30}, {"name": "茶葉蛋", "amount": 13}] if items is None else items}


@pytest.fixture
def db(monkeypatch):
    s = _Session()
    monkeypatch.setattr(einvoice, "SessionLocal", lambda: s)
    return s


def test_新增發票_每列created_at是日期加時間(db):
    got = einvoice._save_invoices([_inv()], source="載具1")
    assert got == (1, 2, [{"item": "禦飯糰", "price": 30, "date": "2026-08-29"},
                          {"item": "茶葉蛋", "price": 13, "date": "2026-08-29"}])
    assert [t.created_at for t in db.added] == [datetime(2026, 8, 29, 12, 38)] * 2


def test_新增發票_保底那筆也帶時間(db):
    einvoice._save_invoices([_inv(items=[])])
    assert db.added[0].created_at == datetime(2026, 8, 29, 12, 38)


def test_新增發票_沒時間是0點_等於原本行為(db):
    inv = _inv(t=None)
    einvoice._save_invoices([inv])
    assert [t.created_at for t in db.added] == [datetime(2026, 8, 29)] * 2
    inv.pop("time")                                     # 舊爬蟲產出的 dict 沒有 time 鍵也照舊
    inv["invoice_no"] = "BB00000002"
    einvoice._save_invoices([inv])
    assert db.added[-1].created_at == datetime(2026, 8, 29)


def test_已存在且是0點_只補時間_不新增不改其他欄位(db):
    old = [_tx("AA00000001", datetime(2026, 8, 29)), _tx("AA00000001", datetime(2026, 8, 29), "茶葉蛋", 13)]
    other = _tx("CC00000003", datetime(2026, 8, 29))
    db.rows = old + [other]
    got = einvoice._save_invoices([_inv()])
    assert got == (0, 0, [])                            # 回傳型態不變、沒有新增
    assert db.added == []
    assert [r.created_at for r in old] == [datetime(2026, 8, 29, 12, 38)] * 2
    assert [(r.item, r.price, r.seller, r.source) for r in old] == \
        [("禦飯糰", 43, "某某商店", "載具1"), ("茶葉蛋", 13, "某某商店", "載具1")]
    assert other.created_at == datetime(2026, 8, 29)    # 別張發票不動
    assert db.commits == 1


def test_已存在但日期不同_不改(db):
    old = _tx("AA00000001", datetime(2026, 8, 28))
    db.rows = [old]
    einvoice._save_invoices([_inv()])
    assert old.created_at == datetime(2026, 8, 28) and db.added == []


def test_已存在且已有時間_不改(db):
    old = _tx("AA00000001", datetime(2026, 8, 29, 9, 1))
    db.rows = [old]
    einvoice._save_invoices([_inv()])
    assert old.created_at == datetime(2026, 8, 29, 9, 1)


def test_已存在但這次沒時間_不改(db):
    old = _tx("AA00000001", datetime(2026, 8, 29))
    db.rows = [old]
    einvoice._save_invoices([_inv(t=None)])
    assert old.created_at == datetime(2026, 8, 29)


def test_fill_invoice_times_只補不新增_回補了幾張(db):
    a, b = _tx("AA00000001", datetime(2026, 8, 29)), _tx("BB00000002", datetime(2026, 8, 29, 9, 1))
    db.rows = [a, b]
    n = einvoice.fill_invoice_times([_inv("AA00000001"), _inv("BB00000002"), _inv("ZZ00000009")])
    assert n == 1
    assert a.created_at == datetime(2026, 8, 29, 12, 38) and b.created_at == datetime(2026, 8, 29, 9, 1)
    assert db.added == [] and db.commits == 1

