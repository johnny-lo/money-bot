"""發票同步打卡高水位 + 缺口補拓。

- get/set_last_covered：單列狀態 repo（id=1）
- build_month_plan：純函式，缺口 → 逐月查詢計畫
- sync_with_backfill：orchestrator，複用 einvoice 的 scraper
- backfill_invoice_times：一次性補舊發票的開立時間（只補時間，不新增、不動高水位）
"""
from datetime import date, datetime, timedelta

import asyncio

from database import SessionLocal
from models import InvoiceSyncState
from einvoice import _scrape_carrier, _save_invoices, _list_carriers, fill_invoice_times, LoginFailed
from autofix import sensors

BACKFILL_CAP_DAYS = 60
BOOTSTRAP_DAYS = 2
TIME_BACKFILL_FROM = date(2026, 4, 21)   # 開始用載具記帳那天；更早的發票不補時間


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


def _scrape_one(phone: str, password: str, entry: dict, headless: bool) -> list[dict]:
    """I/O 邊界：依 plan entry 呼叫既有 async scraper（測試 monkeypatch 此函式）。"""
    if entry["mode"] == "month":
        return asyncio.run(_scrape_carrier(
            phone, password, 1, headless=headless, month=(entry["year"], entry["month"])))
    return asyncio.run(_scrape_carrier(phone, password, entry["days"], headless=headless))


def _entry_label(entry: dict) -> str:
    if entry["mode"] == "month":
        return f"{entry['year']}-{entry['month']:02d} 整月"
    return f"{entry['year']}-{entry['month']:02d} 近 {entry['days']} 天"


def sync_with_backfill(headless: bool = True, today: date | None = None) -> dict:
    """算缺口 → 逐月補抓 → 全成功才推進高水位。回統計 dict（不發 Discord，由呼叫端決定通知）。"""
    today = today or datetime.now().date()
    last = get_last_covered()
    gap_start = (last + timedelta(days=1)) if last else (today - timedelta(days=BOOTSTRAP_DAYS - 1))

    skipped = 0
    cap_floor = today - timedelta(days=BACKFILL_CAP_DAYS)
    if gap_start < cap_floor:
        skipped = (cap_floor - gap_start).days
        gap_start = cap_floor
        print(f"⚠️ 發票補拓：超過 {BACKFILL_CAP_DAYS} 天的 {skipped} 天已跳過（平台多半也查不到）")
    if gap_start > today:
        gap_start = today

    plan = build_month_plan(gap_start, today)
    carriers = _list_carriers()

    lines = [f"🧾 發票補拓（{gap_start} ~ {today}）"]
    failures: list[dict] = []
    all_added: list[dict] = []
    total_new_inv = 0
    if not carriers:
        lines.append("  ⚠️ 未設定任何載具")
    for label, phone, password in carriers:
        masked = f"{phone[:4]}***{phone[-2:]}"
        for entry in plan:
            try:
                invs = _scrape_one(phone, password, entry, headless)
                new_inv, new_items, added = _save_invoices(invs, source=f"載具{label}")
                total_new_inv += new_inv
                all_added.extend(added)
                lines.append(f"  載具{label} {masked} {_entry_label(entry)}："
                             f"抓 {len(invs)} 張、新增 {new_inv} 張")
                sensors.login_ok(label)
            except LoginFailed as e:
                sensors.login_failed(label, masked, e)
                failures.append({"label": label, "masked": masked,
                                 "month": _entry_label(entry), "error": f"LoginFailed: {e}"})
                lines.append(f"  載具{label} {masked} {_entry_label(entry)}：❌ LoginFailed: {e}")
                break   # 同載具其他月份也登不進去，別再燒登入次數（帳號 40 次會鎖）
            except Exception as e:
                failures.append({"label": label, "masked": masked,
                                 "month": _entry_label(entry), "error": f"{type(e).__name__}: {e}"})
                lines.append(f"  載具{label} {masked} {_entry_label(entry)}：❌ {type(e).__name__}: {e}")

    ok = (not failures) and bool(carriers)
    if ok:
        set_last_covered(today)
    lines.append(f"📊 新增 {total_new_inv} 張；高水位{'推進到 ' + str(today) if ok else '未推進'}")
    return {
        "summary": "\n".join(lines),
        "new_items": all_added,
        "ok": ok,
        "failures": failures,
        "last_covered": last,
        "advanced_to": today if ok else None,
        "retry_from": gap_start,
        "skipped_days": skipped,
    }


def backfill_invoice_times(since: date = TIME_BACKFILL_FROM, today: date | None = None,
                           headless: bool = True) -> int:
    """一次性：每個載具從 since 逐月重查到今天，已存在的發票只補開立時間（還是 00:00 的才補）。
    不新增發票、不動高水位。查不到的月份就算了；登入失敗換下一個載具（別燒登入次數）。回補了幾張。

    在容器裡跑：python -c "import invoice_backfill as b; print(b.backfill_invoice_times())"
    """
    today = today or datetime.now().date()
    plan = build_month_plan(since, today)
    filled = 0
    for label, phone, password in _list_carriers():
        masked = f"{phone[:4]}***{phone[-2:]}"
        for entry in plan:
            try:
                n = fill_invoice_times(_scrape_one(phone, password, entry, headless))
                filled += n
                print(f"  載具{label} {masked} {_entry_label(entry)}：補時間 {n} 張", flush=True)
            except LoginFailed as e:
                print(f"  載具{label} {masked}：❌ LoginFailed: {e}，跳過這個載具", flush=True)
                break
            except Exception as e:
                print(f"  載具{label} {masked} {_entry_label(entry)}：⚠️ {type(e).__name__}: {e}", flush=True)
    print(f"🕒 發票補時間：共 {filled} 張", flush=True)
    return filled
