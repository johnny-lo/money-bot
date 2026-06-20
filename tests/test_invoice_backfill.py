from datetime import date, timedelta

from models import InvoiceSyncState
from invoice_backfill import build_month_plan


def test_invoice_sync_state_table_and_columns():
    assert InvoiceSyncState.__tablename__ == "invoice_sync_state"
    cols = {c.name for c in InvoiceSyncState.__table__.columns}
    assert cols == {"id", "last_covered_date", "updated_at"}


def test_plan_same_month():
    assert build_month_plan(date(2026, 6, 15), date(2026, 6, 18)) == [
        {"year": 2026, "month": 6, "mode": "days", "days": 4},
    ]


def test_plan_same_day():
    assert build_month_plan(date(2026, 6, 18), date(2026, 6, 18)) == [
        {"year": 2026, "month": 6, "mode": "days", "days": 1},
    ]


def test_plan_cross_one_month():
    assert build_month_plan(date(2026, 5, 28), date(2026, 6, 3)) == [
        {"year": 2026, "month": 5, "mode": "month"},
        {"year": 2026, "month": 6, "mode": "days", "days": 3},
    ]


def test_plan_cross_two_months():
    assert build_month_plan(date(2026, 4, 20), date(2026, 6, 3)) == [
        {"year": 2026, "month": 4, "mode": "month"},
        {"year": 2026, "month": 5, "mode": "month"},
        {"year": 2026, "month": 6, "mode": "days", "days": 3},
    ]


def test_plan_year_boundary():
    assert build_month_plan(date(2025, 12, 30), date(2026, 1, 2)) == [
        {"year": 2025, "month": 12, "mode": "month"},
        {"year": 2026, "month": 1, "mode": "days", "days": 2},
    ]


def test_plan_bootstrap_two_days():
    # gap_start = today-1 → 當月 days=2（＝現狀行為）
    assert build_month_plan(date(2026, 6, 17), date(2026, 6, 18)) == [
        {"year": 2026, "month": 6, "mode": "days", "days": 2},
    ]


import invoice_backfill as ib


def _patch(monkeypatch, *, last, carriers, scrape_ok=True):
    monkeypatch.setattr(ib, "get_last_covered", lambda: last)
    saved = {}
    monkeypatch.setattr(ib, "set_last_covered", lambda d: saved.update(d=d))
    monkeypatch.setattr(ib, "_list_carriers", lambda: carriers)
    calls = []

    def fake_scrape(phone, password, entry, headless):
        calls.append((phone, entry))
        if not scrape_ok:
            raise RuntimeError("登入失敗")
        return [{"invoice_no": "X", "amount": 1, "date": "2026-06-18", "seller": "S", "items": []}]

    monkeypatch.setattr(ib, "_scrape_one", fake_scrape)
    monkeypatch.setattr(ib, "_save_invoices", lambda invs: (len(invs), len(invs), []))
    return saved, calls


def test_backfill_all_ok_advances(monkeypatch):
    saved, calls = _patch(monkeypatch, last=date(2026, 6, 15),
                          carriers=[(1, "0912345678", "pw")])
    res = ib.sync_with_backfill(today=date(2026, 6, 18))
    assert res["ok"] is True
    assert saved["d"] == date(2026, 6, 18)          # 全成功 → 推進到今天
    assert res["advanced_to"] == date(2026, 6, 18)
    # gap 6/16..6/18 同月 → 一個 days entry；一個載具 → 一次 scrape
    assert len(calls) == 1 and calls[0][1]["mode"] == "days" and calls[0][1]["days"] == 3


def test_backfill_failure_does_not_advance(monkeypatch):
    saved, calls = _patch(monkeypatch, last=date(2026, 6, 15),
                          carriers=[(1, "0912345678", "pw")], scrape_ok=False)
    res = ib.sync_with_backfill(today=date(2026, 6, 18))
    assert res["ok"] is False
    assert "d" not in saved                          # 失敗 → 不推進
    assert res["advanced_to"] is None
    assert res["failures"] and res["retry_from"] == date(2026, 6, 16)


def test_backfill_cap_clamps_and_reports_skipped(monkeypatch):
    saved, calls = _patch(monkeypatch, last=date(2026, 1, 1),
                          carriers=[(1, "0912345678", "pw")])
    res = ib.sync_with_backfill(today=date(2026, 6, 18))
    assert res["skipped_days"] > 0                    # 超過 60 天被夾掉
    assert res["retry_from"] == date(2026, 6, 18) - timedelta(days=60)


def test_backfill_bootstrap_when_no_state(monkeypatch):
    saved, calls = _patch(monkeypatch, last=None,
                          carriers=[(1, "0912345678", "pw")])
    res = ib.sync_with_backfill(today=date(2026, 6, 18))
    # 無紀錄 → gap_start = 今天-1 → 當月 days=2
    assert calls[0][1] == {"year": 2026, "month": 6, "mode": "days", "days": 2}
