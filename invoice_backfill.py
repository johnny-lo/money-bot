"""發票同步打卡高水位 + 缺口補拓。

- get/set_last_covered：單列狀態 repo（id=1）
- build_month_plan：純函式，缺口 → 逐月查詢計畫
- sync_with_backfill：orchestrator，複用 einvoice 的 scraper
"""
from datetime import date, datetime, timedelta

from database import SessionLocal
from models import InvoiceSyncState


def build_month_plan(gap_start: date, today: date) -> list[dict]:
    """缺口 [gap_start..today] → 逐月查詢計畫。

    前月（< today 所在月）：整月 month= 查；當月：預設查 + days 回推到 gap_start。
    政府站限制每次查詢須同月，故以月為單位。
    """
    plan: list[dict] = []
    y, m = gap_start.year, gap_start.month
    while (y, m) < (today.year, today.month):
        plan.append({"year": y, "month": m, "mode": "month"})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    current_first = today.replace(day=1)
    since_current = max(gap_start, current_first)
    days = (today - since_current).days + 1
    plan.append({"year": today.year, "month": today.month, "mode": "days", "days": days})
    return plan


def get_last_covered() -> date | None:
    """已成功涵蓋到的最後一天；無紀錄回 None。"""
    db = SessionLocal()
    try:
        row = db.query(InvoiceSyncState).filter(InvoiceSyncState.id == 1).first()
        return row.last_covered_date if row else None
    finally:
        db.close()


def set_last_covered(d: date) -> None:
    """upsert id=1 的高水位。"""
    db = SessionLocal()
    try:
        row = db.query(InvoiceSyncState).filter(InvoiceSyncState.id == 1).first()
        if row is None:
            row = InvoiceSyncState(id=1, last_covered_date=d)
            db.add(row)
        else:
            row.last_covered_date = d
        db.commit()
    finally:
        db.close()
