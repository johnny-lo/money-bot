# 發票同步打卡+智能補拓 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 發票同步記錄「已涵蓋到哪一天」高水位，每次同步自動算缺口並補抓（本月加大 days、跨月逐月 month=），不再只抓前兩天；失敗在發票通知頻道彈卡、高水位不推進。

**Architecture:** 新增單列表 `invoice_sync_state` 記 `last_covered_date`。純函式 `build_month_plan(gap_start, today)` 把缺口拆成逐月查詢計畫（政府站同月限制）。orchestrator `sync_with_backfill()` 複用既有 `einvoice._scrape_carrier`/`_save_invoices`/`_list_carriers`，全成功才推進高水位。排程改呼叫它 + 開機後 3 分鐘背景補一次。

**Tech Stack:** Python 3 / SQLAlchemy(Postgres) / APScheduler / discord.py / Playwright（既有 scraper，本計畫不改其內部）。

**Spec:** [docs/superpowers/specs/2026-06-18-invoice-backfill-design.md](../specs/2026-06-18-invoice-backfill-design.md)

## Global Constraints

- 測試在容器內跑：`docker exec -w /app money-bot python -m pytest <檔> -v`（host 無 python）。
- 回填上限 `BACKFILL_CAP_DAYS = 60`；bootstrap（無紀錄）`gap_start = today - 1`（＝現狀 days=2）。
- 去重靠 `invoice_no`（`_save_invoices`），over-scrape 安全。
- 手動 `/抓發票 [天數]` 不動、不碰高水位狀態。
- 新表由 `main.py:28` `create_all` 自動建，免 migration（`models.py` 已在 main.py:9 經 categorize import）。
- 每個功能 commit 更新 README + CODEBASE（最後一個 task）。

---

## File Structure

新增：
- `invoice_backfill.py` — 純函式 `build_month_plan` + 狀態 repo `get_last_covered`/`set_last_covered` + orchestrator `sync_with_backfill` + I/O 邊界 `_scrape_one`
- `tests/test_invoice_backfill.py` — build_month_plan（純）+ sync_with_backfill（monkeypatch 編排）+ 狀態 model shape

修改：
- `models.py` — 加 `Date` import + `InvoiceSyncState`
- `discordbot/embeds.py` — 加 `invoice_sync_failed_embed`
- `discordbot/reports.py` — 加 `notify_invoice_failure`
- `discordbot/__init__.py` — 匯出 `notify_invoice_failure`
- `main.py` — 排程改呼叫 `sync_with_backfill` + 開機補拓 job + 通知決策
- `tests/test_video_embeds.py` 模式參考（純呈現 embed 測試寫法）
- `README.md` / `CODEBASE.md` — 文件

---

## Task 1: 資料模型 + 狀態 repo

**Files:**
- Modify: `models.py`（檔尾 + 第 1 行 import 加 `Date`）
- Create: `invoice_backfill.py`（先只放狀態 repo）
- Test: `tests/test_invoice_backfill.py`

**Interfaces:**
- Produces: `InvoiceSyncState`（table `invoice_sync_state`，欄 `id/last_covered_date/updated_at`）；
  `get_last_covered() -> datetime.date | None`、`set_last_covered(d: datetime.date) -> None`

- [ ] **Step 1: 寫失敗測試（model shape）**

`tests/test_invoice_backfill.py`：
```python
from models import InvoiceSyncState


def test_invoice_sync_state_table_and_columns():
    assert InvoiceSyncState.__tablename__ == "invoice_sync_state"
    cols = {c.name for c in InvoiceSyncState.__table__.columns}
    assert cols == {"id", "last_covered_date", "updated_at"}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_backfill.py -v`
Expected: FAIL — `ImportError: cannot import name 'InvoiceSyncState' from 'models'`

- [ ] **Step 3: 加 model**

`models.py` 第 1 行 import 加 `Date`：
```python
from sqlalchemy import Column, Integer, String, DateTime, Date, Float, ForeignKey, func
```
`models.py` 檔尾加：
```python


class InvoiceSyncState(Base):
    """發票同步打卡高水位（單列，id 恆 = 1）。"""
    __tablename__ = "invoice_sync_state"

    id = Column(Integer, primary_key=True)             # 永遠 1
    last_covered_date = Column(Date, nullable=True)    # 已成功涵蓋到的最後一天（含）；NULL=尚未 bootstrap
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_backfill.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 寫狀態 repo**

`invoice_backfill.py`（新檔）：
```python
"""發票同步打卡高水位 + 缺口補拓。

- get/set_last_covered：單列狀態 repo（id=1）
- build_month_plan：純函式，缺口 → 逐月查詢計畫
- sync_with_backfill：orchestrator，複用 einvoice 的 scraper
"""
from datetime import date, datetime, timedelta

from database import SessionLocal
from models import InvoiceSyncState


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
```

- [ ] **Step 6: 容器內 roundtrip 驗證（repo 無單元測試，比照 food/recipe repo 姿態）**

Run:
```bash
docker exec -w /app money-bot python -c "
from datetime import date
from invoice_backfill import get_last_covered, set_last_covered
set_last_covered(date(2026,6,15))
print('roundtrip:', get_last_covered())
"
```
Expected: `roundtrip: 2026-06-15`
（這會在正式 DB 建一列 invoice_sync_state；無害，下個 task 的真實同步會正常推進它。）

- [ ] **Step 7: Commit**

```bash
git add models.py invoice_backfill.py tests/test_invoice_backfill.py
git commit -m "feat(invoice): invoice_sync_state 表 + 高水位 repo

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: build_month_plan（純函式，缺口→逐月計畫）

**Files:**
- Modify: `invoice_backfill.py`
- Test: `tests/test_invoice_backfill.py`

**Interfaces:**
- Produces: `build_month_plan(gap_start: date, today: date) -> list[dict]`，每筆為
  `{"year":int,"month":int,"mode":"month"}`（前月整月）或
  `{"year":int,"month":int,"mode":"days","days":int}`（當月，days 回推到 gap_start）

- [ ] **Step 1: 寫失敗測試**

`tests/test_invoice_backfill.py` 追加：
```python
from datetime import date
from invoice_backfill import build_month_plan


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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_backfill.py -k plan -v`
Expected: FAIL — `ImportError: cannot import name 'build_month_plan'`

- [ ] **Step 3: 實作**

`invoice_backfill.py` 加（在 import 之後、repo 之前或之後皆可）：
```python
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_backfill.py -k plan -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add invoice_backfill.py tests/test_invoice_backfill.py
git commit -m "feat(invoice): build_month_plan——缺口拆逐月查詢計畫（純函式）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: sync_with_backfill orchestrator

**Files:**
- Modify: `invoice_backfill.py`
- Test: `tests/test_invoice_backfill.py`

**Interfaces:**
- Consumes: `build_month_plan`、`get_last_covered`/`set_last_covered`、
  `einvoice._scrape_carrier`/`_save_invoices`/`_list_carriers`
- Produces: `BACKFILL_CAP_DAYS = 60`、`BOOTSTRAP_DAYS = 2`、
  `_scrape_one(phone, password, entry: dict, headless: bool) -> list[dict]`（I/O 邊界，測試 monkeypatch 它）、
  `sync_with_backfill(headless=True, today=None) -> dict`，回
  `{"summary":str,"new_items":list,"ok":bool,"failures":list,"last_covered":date|None,"advanced_to":date|None,"retry_from":date,"skipped_days":int}`

- [ ] **Step 1: 寫失敗測試（monkeypatch 編排）**

`tests/test_invoice_backfill.py` 追加：
```python
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
```
（檔頂若還沒 import `timedelta`，加 `from datetime import timedelta`。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_backfill.py -k backfill -v`
Expected: FAIL — `AttributeError: module 'invoice_backfill' has no attribute 'sync_with_backfill'`

- [ ] **Step 3: 實作**

`invoice_backfill.py` 加 import 與 orchestrator：
```python
from einvoice import _scrape_carrier, _save_invoices, _list_carriers
import asyncio

BACKFILL_CAP_DAYS = 60
BOOTSTRAP_DAYS = 2


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
                new_inv, new_items, added = _save_invoices(invs)
                total_new_inv += new_inv
                all_added.extend(added)
                lines.append(f"  載具{label} {masked} {_entry_label(entry)}："
                             f"抓 {len(invs)} 張、新增 {new_inv} 張")
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_backfill.py -v`
Expected: PASS（全部，含 model/plan/backfill）

- [ ] **Step 5: 全套回歸 + Commit**

Run: `docker exec -w /app money-bot python -m pytest tests/ -q`
Expected: 全 PASS

```bash
git add invoice_backfill.py tests/test_invoice_backfill.py
git commit -m "feat(invoice): sync_with_backfill——缺口逐月補、全成功才推進、cap 60

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 失敗卡片 embed + notify wrapper

**Files:**
- Modify: `discordbot/embeds.py`
- Modify: `discordbot/reports.py`
- Modify: `discordbot/__init__.py`
- Test: `tests/test_invoice_failed_embed.py`

**Interfaces:**
- Consumes: `sync_with_backfill` 的回傳 dict（`summary`/`failures`/`last_covered`/`retry_from`）
- Produces: `discordbot.embeds.invoice_sync_failed_embed(result: dict) -> discord.Embed`；
  `discordbot.notify_invoice_failure(result: dict) -> None`

- [ ] **Step 1: 寫失敗測試（embed 純呈現）**

`tests/test_invoice_failed_embed.py`：
```python
from datetime import date
from discordbot.embeds import invoice_sync_failed_embed


def test_failed_embed_lists_failure_and_retry():
    result = {
        "summary": "🧾 發票補拓（2026-06-16 ~ 2026-06-18）\n  載具2 0987***21 2026-06 近 3 天：❌ RuntimeError: 登入失敗",
        "failures": [{"label": 2, "masked": "0987***21", "month": "2026-06 近 3 天",
                      "error": "RuntimeError: 登入失敗"}],
        "last_covered": date(2026, 6, 15),
        "retry_from": date(2026, 6, 16),
    }
    e = invoice_sync_failed_embed(result)
    blob = e.title + (e.description or "") + " ".join(f"{f.name}{f.value}" for f in e.fields)
    assert "失敗" in e.title
    assert "登入失敗" in blob
    assert "未推進" in blob
    assert "2026-06-15" in blob and "2026-06-16" in blob   # 仍停在 + 下次重抓起點
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_failed_embed.py -v`
Expected: FAIL — `ImportError: cannot import name 'invoice_sync_failed_embed'`

- [ ] **Step 3a: embeds.py**

`discordbot/embeds.py` 檔尾加（`COLOR_WARN`、`discord` 已有；此 embed 不用 datetime）：
```python
def invoice_sync_failed_embed(result: dict) -> discord.Embed:
    """發票同步失敗卡（發到 #🧾-發票通知）。"""
    e = discord.Embed(title="⚠️ 發票同步失敗", color=COLOR_WARN)
    e.description = f"```\n{result.get('summary', '')[:3500]}\n```"
    last = result.get("last_covered")
    retry = result.get("retry_from")
    note = f"涵蓋進度未推進（仍停在 {last if last else '無紀錄'}）"
    if retry:
        note += f"\n→ 下次自動重抓 {retry} ~ 今天"
    e.add_field(name="狀態", value=note, inline=False)
    e.set_footer(text="🐉 發票補拓")
    return e
```

- [ ] **Step 3b: 跑 embed 測試確認通過**

Run: `docker exec -w /app money-bot python -m pytest tests/test_invoice_failed_embed.py -v`
Expected: PASS（1 passed）

- [ ] **Step 3c: reports.py notify wrapper**

`discordbot/reports.py`：找到 `from .embeds import (...)`（reports 目前用到 `COLOR_WARN`、`build_items_embed` 等）加上 `invoice_sync_failed_embed`；在 `notify_invoice_sync` 之後加：
```python
def notify_invoice_failure(result: dict) -> None:
    """發票同步失敗 → 發失敗卡到 #🧾-發票通知。"""
    chan_id = os.getenv("DISCORD_INVOICE_CHANNEL_ID")
    if not chan_id:
        return
    post_embeds_sync(int(chan_id), [invoice_sync_failed_embed(result)])
```

- [ ] **Step 3d: __init__.py 匯出**

`discordbot/__init__.py`：在匯入 `notify_invoice_sync` 處同列加 `notify_invoice_failure`，並加進 `__all__`。

- [ ] **Step 4: 全套回歸**

Run: `docker exec -w /app money-bot python -m pytest tests/ -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add discordbot/embeds.py discordbot/reports.py discordbot/__init__.py tests/test_invoice_failed_embed.py
git commit -m "feat(invoice): 失敗卡片 embed + notify_invoice_failure（發票通知頻道）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 排程接線（main.py）

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `invoice_backfill.sync_with_backfill`、`discordbot.notify_invoice_failure`、既有 `notify_invoice_sync`

- [ ] **Step 1: import + 通知決策 helper**

`main.py` import 區加：
```python
from datetime import datetime, timedelta
from invoice_backfill import sync_with_backfill
```
並把既有 `from discordbot import (... notify_invoice_sync ...)` 那塊加上 `notify_invoice_failure`。
（注意：`_weekly_pipeline` 內原本有 `from datetime import datetime as _dt`，可保留或改用頂部 import，不衝突。）

在 scheduler 定義前加：
```python
def _notify_invoice_result(result, *, quiet_if_empty=False):
    """全成功→成功摘要（quiet_if_empty 時 0 新增不發）；失敗→失敗卡。"""
    if not result["ok"]:
        notify_invoice_failure(result)
    elif result["new_items"] or not quiet_if_empty:
        notify_invoice_sync(result["summary"], result["new_items"])
```

- [ ] **Step 2: 改 daily / weekly 走 backfill**

`main.py` `_daily_invoice_with_notify`：
```python
def _daily_invoice_with_notify():
    """週一到週六 21:00 補拓同步後通知 Discord #🧾-發票通知。"""
    result = sync_with_backfill()
    _notify_invoice_result(result)
```
`_weekly_pipeline` 內第一段（原 `result = run_invoice_sync(days=2)` + `notify_invoice_sync(...)`）改：
```python
    try:
        result = sync_with_backfill()
        _notify_invoice_result(result)
    except Exception as e:
        print(f"⚠️ 週日發票同步失敗：{e}")
```

- [ ] **Step 3: 開機後 3 分鐘背景補拓 job**

`main.py` `startup_event` 內、`scheduler.start()` 之後加：
```python
    def _startup_catchup():
        result = sync_with_backfill()
        _notify_invoice_result(result, quiet_if_empty=True)   # 開機只在有新發票或失敗才發卡
    scheduler.add_job(_startup_catchup, "date",
                      run_date=datetime.now() + timedelta(minutes=3), id="startup_catchup")
    print("⏰ 已排程：開機後 3 分鐘背景發票補拓")
```

- [ ] **Step 4: import 預檢 + 全套回歸**

Run:
```bash
docker exec -w /app money-bot python -c "import main" && echo OK
docker exec -w /app money-bot python -m pytest tests/ -q
```
Expected: `OK` + 全 PASS

- [ ] **Step 5: Commit + 重啟**

```bash
git add main.py
git commit -m "feat(invoice): 排程改走 sync_with_backfill + 開機後 3 分鐘背景補拓

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
docker restart money-bot
```
等 `Application startup complete`（背景輪詢，~30–90s）。

- [ ] **Step 6: 真實補拓 smoke（手動觸發一次，不等排程）**

先把高水位設成幾天前製造缺口，再實跑（會真的登入抓發票、寫正式 DB，去重安全）：
```bash
docker exec -w /app money-bot python -c "
from datetime import date, timedelta
from invoice_backfill import set_last_covered, sync_with_backfill, get_last_covered
set_last_covered(date.today() - timedelta(days=3))    # 製造 3 天缺口
res = sync_with_backfill()
print('ok=', res['ok'], '| advanced_to=', res['advanced_to'], '| skipped=', res['skipped_days'])
print('high-water now:', get_last_covered())
print(res['summary'][:600])
"
```
Expected: `ok= True`、`advanced_to=` 今天、`high-water now:` 今天；summary 顯示載具×當月 days=4 的抓取結果。
（若某載具登入失敗 → `ok= False`、高水位停在 3 天前，屬正常的失敗路徑，會在頻道發失敗卡。）

- [ ] **Step 7（可選）：跨月回填驗證（spec §7 平台 retention 深度）**

驗證 `month=` 真能查到上個月（決定 60 天上限是否「打得到」）。慢、會多次登入：
```bash
docker exec -w /app money-bot python -c "
from datetime import date, timedelta
from invoice_backfill import set_last_covered, sync_with_backfill, get_last_covered
set_last_covered(date.today().replace(day=1) - timedelta(days=2))   # 缺口跨到上個月底
res = sync_with_backfill()
print('ok=', res['ok']); print(res['summary'][:800])
"
```
Expected: summary 出現「上月 整月」那行且抓到張數 > 0 → 平台回得到上月。
若上月那行 `❌`/0 張 → 平台對更舊月份的 retention 有限，60 天上限只是「盡力」，打不到的月份會落在失敗卡（已知限制，記入 CODEBASE）。

---

## Task 6: 文件（README + CODEBASE）

**Files:**
- Modify: `README.md`、`CODEBASE.md`

- [ ] **Step 1: 讀現況**

Run: `grep -n "抓發票\|發票\|invoice\|21:00\|資料表\|create_all" README.md CODEBASE.md | head -40`

- [ ] **Step 2: README.md**

在「電子發票自動同步」段補：自動補拓漏抓天數（記 `last_covered_date` 高水位，每次同步算缺口、本月加大 days、跨月逐月補，上限 60 天）；失敗會在 `#🧾-發票通知` 頻道發失敗卡、高水位不推進、下次自動重抓；開機後 3 分鐘背景補拓一次。

- [ ] **Step 3: CODEBASE.md**

補：
- 模組 `invoice_backfill.py`：`build_month_plan`（純）、`get/set_last_covered`、`sync_with_backfill`、`_scrape_one`。
- 資料表 `invoice_sync_state`（id=1 單列、last_covered_date、updated_at）。
- 排程：daily/weekly 改走 `sync_with_backfill`；新增開機後 3 分鐘 `startup_catchup` 一次性 job。
- 失敗卡：`invoice_sync_failed_embed` + `notify_invoice_failure`。

- [ ] **Step 4: Commit**

```bash
git add README.md CODEBASE.md
git commit -m "docs: 發票智能補拓——README + CODEBASE

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 收尾驗證

- [ ] `docker exec -w /app money-bot python -m pytest tests/ -q` 全 PASS。
- [ ] `docker exec -w /app money-bot python -c "import main"` 不崩；重啟後 `Application startup complete` + Bot 上線。
- [ ] 真實補拓 smoke：製造缺口 → `sync_with_backfill()` → 高水位推進到今天（或失敗發卡、不推進）。
- [ ] `git log --oneline -6` 看到 6 個小步 commit。

## 不做（YAGNI）

逐日打卡表、打卡日曆 UI、per-carrier 獨立高水位、手動指令納入狀態、平台 retention 自動探測、
`_scrape_carrier` 內部重構（多月一次登入）——backfill 罕見，逐月各自登入可接受。
