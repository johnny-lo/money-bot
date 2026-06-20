# 發票同步「打卡 + 智能補拓」設計 spec

- 日期：2026-06-18
- 分支：feat/mobile-pwa-frontend
- 狀態：設計定稿，待寫實作計畫（writing-plans）

## 目的

現在抓發票排程固定 `days=2`，只要機器/網站某幾天沒成功同步，那幾天的發票就**永遠漏掉**。
改成：內部記錄「已成功涵蓋到哪一天」（打卡高水位），每次同步**自動算出缺口並補抓**，
不再受限於只抓前兩天。**隱形機制、不做任何 UI。**

## 已定決策（brainstorming 結論）

1. **隱形智能補拓，不做 UI**（無打卡日曆、無前端）。
2. **方案 A：單一高水位 `last_covered_date`**（非逐日打卡表、非每次盲抓固定視窗）。
3. **回填上限 = 60 天**。超過則只補 60 天內、推進到今天，並明確 log 跳過的天數（不靜默截斷）。
4. **失敗要在 `#🧾-發票通知` 頻道彈一張失敗卡片**；高水位不推進。
5. 手動 `/抓發票 [天數]` 指令**維持原樣**，不碰高水位狀態（自動補拓才是狀態擁有者）。

## 現有機制關鍵事實（來自 einvoice.py，設計所依據）

- **`days` 是客端早停，不是查詢參數**：政府站預設回**整個本月**發票（日期由新到舊），
  `_scrape_carrier(month=None)` 只是讀到比 `today-(days-1)` 舊的就停翻頁（`einvoice.py:404-405`、`_parse_current_page` 的 `since` 早停）。
  → **本月內漏天不需回溯查詢**，把 `since` 往回拉到缺口起點即可，本月資料本來就在預設畫面。
- **跨月要逐月查（平台限制）**：`_scrape_carrier(month=(y,m))` 走 `_set_query_month` 把日期選擇器設成該單月。
  註解明載**政府站「每次查詢區間須在同一個月」**（`einvoice.py:360-366`）。此 `month=` 管路已寫好，
  但公開 API `sync_invoices()` 沒接出來（只傳 `days`）。
- **去重靠 `invoice_no`**（`_save_invoices` `einvoice.py:474`）：重疊/重抓同一張會跳過 → **over-scrape 安全、不重複計帳**。
- **目前無任何同步成功紀錄**；排程固定 `days=2`（`main.py` `_daily_invoice_with_notify` / `_weekly_pipeline`）。
- 多載具：`_list_carriers()` 從 `EINVOICE_PHONE_n/PASSWORD_n` 蒐集；`sync_invoices` 逐載具跑、單載具失敗不影響其他。

## 1. 資料模型（models.py 新增一張單列表）

```python
from sqlalchemy import Date  # 需新增 import

class InvoiceSyncState(Base):
    """發票同步打卡高水位（單列，id 恆 = 1）。"""
    __tablename__ = "invoice_sync_state"
    id = Column(Integer, primary_key=True)             # 永遠 1
    last_covered_date = Column(Date, nullable=True)    # 已成功涵蓋到的最後一天（含）；NULL=尚未 bootstrap
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```
- 新表 → `main.py:28` `create_all` 開機自動建，免 migration。
- repo（放 `einvoice.py` 或新 `invoice_state.py`）：`get_last_covered() -> date | None`、`set_last_covered(d: date) -> None`（upsert id=1）。

## 2. 核心：缺口 → 查詢計畫 → 執行 → 推進高水位

### 純函式 `build_month_plan(gap_start, today) -> list[dict]`

把缺口 `[gap_start … today]` 拆成逐月查詢描述（政府站同月限制）：
- `gap_start.month` 到 `today` 前一個月：每個月 `{"year":y,"month":m,"mode":"month"}`（整月查，`month=(y,m)`）。
- 當月（today 所在月）：`{"year":Y,"month":M,"mode":"days","days":D}`，
  其中 `since_current = max(gap_start, 當月1號)`、`D = (today - since_current).days + 1`。
- 同月情形：只回一筆 `mode:"days"`。
- 純函式、不碰 DB/網路 → 主力測試對象。

### Orchestrator `sync_with_backfill(headless=True) -> dict`

```
today = datetime.now().date()                      # 與 einvoice 現有 datetime.now() 一致（TZ 見下）
last  = get_last_covered()
gap_start = (last + 1天) if last else (today - 1天) # bootstrap：首跑＝今天+昨天，不暴抓
capped    = today - 60天
skipped   = 0
if gap_start < capped:
    skipped = (capped - gap_start).days
    gap_start = capped                              # 上限夾擠（log skipped，不靜默）
if gap_start > today: gap_start = today

plan = build_month_plan(gap_start, today)
results = []                                        # 每筆 = (carrier_label, masked, month_desc, ok, detail)
for label, phone, password in _list_carriers():
    for entry in plan:
        try:
            if entry["mode"] == "month":
                invs = scrape(month=(entry["year"], entry["month"]))
            else:
                invs = scrape(days=entry["days"])
            new_inv, new_items, added = _save_invoices(invs)
            results.append(ok=True, ...)
        except Exception as e:
            results.append(ok=False, error=e)

all_ok = all(r.ok for r in results)
if all_ok:
    set_last_covered(today)                         # 全成功才推進
# 不論成敗都回統計；失敗清單給卡片用
return {"summary": ..., "new_items": all_added, "ok": all_ok,
        "failures": [r for r in results if not r.ok],
        "advanced_to": today if all_ok else last,
        "skipped_days": skipped}
```

關鍵性質：
- 本月漏天被 `days` 的 `since` 自然涵蓋；跨月缺口逐月 `month=` 補。
- 去重 → 重疊/重抓全安全，不重複計帳。
- 沒發票的日子也算涵蓋（有去看＝打卡），高水位照推進。
- 任一 (載具×月) 失敗 → 不推進 → 下次自動重抓整段。

### 與 `_scrape_carrier` 的對接
沿用既有簽名 `_scrape_carrier(phone, password, days, month=None)`：當月用 `days=entry["days"]`、
前月用 `month=(y,m)`（`days` 此時被忽略，傳 1 即可）。**不改 `_scrape_carrier` 內部。**

## 3. 排程接線（main.py）

- `_daily_invoice_with_notify`（每天 21:00）、`_weekly_pipeline`（週日 21:00）裡的
  `run_invoice_sync(days=2)` → 改呼叫 `sync_with_backfill()`，並依結果決定發成功摘要或失敗卡片（見 §4）。
- **開機補拓**：`startup_event` 用 APScheduler 一次性 `date` trigger 排在 `now + 3 分鐘`（不卡開機就緒），
  跑 `sync_with_backfill()`；**只有「有新發票」或「失敗」才發卡**（避免每次開機洗「0 新增」）。
- 手動 `/抓發票 [天數]`：**完全不動**（仍走 `sync_invoices(days=...)`，不碰 `invoice_sync_state`）。

## 4. 失敗處理 + 卡片

- **上限**：`gap_start` 夾到 `today-60`；`skipped_days>0` 時 `print` 警告「超過 60 天的 N 天已跳過（平台多半也查不到）」。
- **失敗卡片**（`#🧾-發票通知`）：任一 (載具×月) 失敗就發。新 embed builder `invoice_sync_failed_embed(result)`：
  ```
  ⚠️ 發票同步失敗
  載具1 0912***34：✅ 新增 3 張
  載具2 0987***21：❌ 登入失敗 - RuntimeError: CAPTCHA 連續 4 次辨識失敗
  涵蓋進度未推進（仍停在 2026-06-15）→ 下次自動重抓 06-16 ~ 今天
  ```
  經既有 discordbot 通知管路送到 `DISCORD_INVOICE_CHANNEL_ID`（比照 `notify_invoice_sync`）。
- **全成功** → 沿用現有 `notify_invoice_sync(summary, new_items)` 成功摘要卡（含「新增明細」second embed）。
- 通知決策集中在 main.py 的三個 wrapper（daily/weekly/startup），orchestrator 只回資料不發訊息（純度）。

## 5. 測試（沿用本 repo 純單元姿態）

- **`build_month_plan`**（主力，純函式）：同月、跨 1 月、跨 2 月、bootstrap、上限夾擠各一 case，斷言回的月份清單與當月 `days`。
- **`sync_with_backfill` 編排**：monkeypatch `_scrape_carrier`、`_save_invoices`、`get/set_last_covered`、`_list_carriers` →
  驗證①依 plan 對每載具每月呼叫、②全成功才 `set_last_covered(today)`、③有失敗不推進且 `ok=False`+`failures` 有料。
- **model shape**：`InvoiceSyncState.__table__.columns` introspection。
- **狀態 repo**：get/set roundtrip（FakeSession 或既有 DB 測試姿態）。
- **失敗卡片 embed**：`invoice_sync_failed_embed` 純呈現，斷言列出失敗載具 + 「未推進」+ 下次重抓區間。

## 6. 不做（YAGNI / 明確排除）

逐日打卡表、打卡日曆 UI（前端/Discord 視圖）、per-carrier 獨立高水位（用單一高水位 + 全成功才推進）、
手動指令納入狀態追蹤、平台 retention 自動探測。

## 7. 實作期要驗證的點

- **平台回溯深度**：用 `month=(y,m)` 實際往前 1、2 個月查，確認政府站還回得到（決定 60 天上限是否「打得到」）。
  測前一個月應該 OK；更舊的可能被平台擋——若打不到，60 天上限只是「盡力」，打不到的月份會落在失敗卡片裡。
- **時區**：`datetime.now().date()` 在 container 的 TZ。排程器用 `Asia/Taipei`；確認 `now()` 取到的是台北日期
  （與 einvoice 既有 `datetime.now()` 用法一致即可，但跨午夜的邊界要留意）。
- **bootstrap 首跑**：`invoice_sync_state` 空表時 `get_last_covered()` 回 None → gap_start=今天-1，行為＝現狀，不暴抓。

## 8. 文件（commit 時更新）

- `README.md`：抓發票段補「自動補拓漏抓的天數（打卡高水位，上限 60 天）+ 失敗會在發票通知頻道發卡」。
- `CODEBASE.md`：新表 `invoice_sync_state`、`sync_with_backfill`/`build_month_plan`、排程改動、失敗卡片 embed。
