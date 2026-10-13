"""一次性補舊發票時間：逐月重查、只補時間（不新增、不動高水位）。不連網、不登入。"""
from datetime import date, time

import pytest

import invoice_backfill as ib
from einvoice import LoginFailed


def _inv(no):
    return {"invoice_no": no, "amount": 1, "date": "2026-05-01", "seller": "S", "items": [], "time": time(12, 0)}


@pytest.fixture
def wired(monkeypatch):
    calls, filled = [], []
    monkeypatch.setattr(ib, "_list_carriers", lambda: [(1, "0900000001", "pw"), (2, "0900000002", "pw")])

    def scrape(phone, password, entry, headless):
        calls.append((phone, entry))
        return [_inv(f"{phone[-1]}{entry['month']:02d}")]
    monkeypatch.setattr(ib, "_scrape_one", scrape)

    def fill(invs):
        filled.append([i["invoice_no"] for i in invs])
        return len(invs)
    monkeypatch.setattr(ib, "fill_invoice_times", fill)

    def boom(*a, **k):
        raise AssertionError("補時間不得新增發票、不得動高水位")
    monkeypatch.setattr(ib, "_save_invoices", boom)
    monkeypatch.setattr(ib, "set_last_covered", boom)
    return calls, filled


def test_逐月計畫_每個載具從起始日查到今天_只補時間(wired):
    calls, filled = wired
    n = ib.backfill_invoice_times(since=date(2026, 4, 21), today=date(2026, 6, 3))
    assert n == 6
    plan = [{"year": 2026, "month": 4, "mode": "month"}, {"year": 2026, "month": 5, "mode": "month"},
            {"year": 2026, "month": 6, "mode": "days", "days": 3}]
    assert calls == [("0900000001", e) for e in plan] + [("0900000002", e) for e in plan]
    assert filled[0] == ["104"] and len(filled) == 6


def test_預設起始日是開始用載具那天():
    assert ib.TIME_BACKFILL_FROM == date(2026, 4, 21)


def test_查不到的月份算了_登入失敗就換下一個載具(wired, monkeypatch):
    calls, filled = wired

    def scrape(phone, password, entry, headless):
        calls.append((phone, entry["month"]))
        if phone.endswith("1") and entry["month"] == 4:
            raise RuntimeError("查不到")
        if phone.endswith("2"):
            raise LoginFailed(["第1次：帳密錯誤"])
        return [_inv("X")]
    monkeypatch.setattr(ib, "_scrape_one", scrape)
    n = ib.backfill_invoice_times(since=date(2026, 4, 21), today=date(2026, 6, 3))
    assert n == 2                                            # 載具1 的 5、6 月
    assert calls == [("0900000001", 4), ("0900000001", 5), ("0900000001", 6), ("0900000002", 4)]
