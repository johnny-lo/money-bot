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
