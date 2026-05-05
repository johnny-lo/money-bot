# Codebase Index (AI Quick Reference)

> 供 AI 快速理解專案結構，每次 commit 時更新。
> Last updated: 2026-05-05

## Stack

Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL 15 / Gemini API / LINE Bot SDK 2.4.3 / discord.py / APScheduler / Playwright (Chromium) / ECharts 5 / Docker Compose + ngrok

## File Map

```
.
├── main.py              # 入口：FastAPI app 建立、DB 初始化、APScheduler 排程、Discord Bot 啟動
├── core.py              # 核心業務邏輯：文字指令解析/處理、圖片記帳、訊息路由 + Data API（Discord embeds 用）
├── line_handler.py      # LINE Bot：webhook /callback、文字/圖片訊息事件處理（純文字介面）
├── discord_handler.py   # Discord Bot：14 個 Slash Commands + Embeds、圖片附件 on_message 處理
├── gemini.py            # Gemini API 封裝：gemini_text()、gemini_image()、generate_persona_comment()
├── database.py          # SQLAlchemy engine/SessionLocal/Base 建立（讀 DATABASE_URL）
├── models.py            # ORM 模型：Transaction(支出)、Income(收入)、RecurringRecord(固定收支)
├── categorize.py        # AI 分類：run_weekly_categorization() 批次分類未分類帳目（封閉 12 類：三餐/飲料/零食/食材/油費/停車/居家用品/個人保養/醫療/服飾/娛樂/其他）
├── recurring.py         # 固定收支：run_daily_recurring() 每日自動寫入到期項目
├── auth.py              # Token 驗證：generate_report_token()、validate_report_token()、require_token dependency
├── einvoice.py          # 財政部電子發票同步：Playwright 登入 → CAPTCHA(Gemini) → 抓發票 → 寫 transactions。`sync_invoices()` 回傳 `{"summary": str, "new_items": list[dict]}`，支援多組載具（EINVOICE_PHONE_1/2 + PASSWORD_1/2）
├── persona.md           # AI 角色設定：木須龍(台灣配音風格)，記帳後生成角色回應
├── resource/            # Discord 頻道歡迎 banner 圖（手動放入，由 _setup_discord 一次性上傳；已 .gitignore 不入版本控制）
├── requirements.txt     # Python 依賴
├── Dockerfile           # python:3.11-slim，pip install → uvicorn 啟動
├── docker-compose.yml   # 三個服務：app(127.0.0.1:8000)、db(PostgreSQL，僅 docker network)、ngrok(127.0.0.1:4040 inspector + tunnel)
├── routes/
│   ├── __init__.py
│   ├── report.py        # 報表 API：/api/report/monthly|category|summary|ledger + /report 頁面
│   └── record.py        # CRUD API：POST/PUT/DELETE /api/record（供網頁報表使用）
└── templates/
    └── report.html      # 互動式報表 SPA：ECharts 圖表 + 流水帳 CRUD（純前端 JS）
```

## DB Schema

| Table | Columns | Notes |
|-------|---------|-------|
| `transactions` | id(PK), item(str), price(int), category(str?), invoice_no(str?), created_at(datetime) | 支出。invoice_no 是發票去重 key（einvoice 自動帶入；手動記帳為 NULL） |
| `incomes` | id(PK), item(str), amount(int), category(str?), created_at(datetime) | 收入 |
| `recurring_records` | id(PK), type("expense"/"income"), item, amount, category?, day_of_month(1-28), active(1/0), created_at | 固定收支 |

main.py 啟動時自動 `CREATE TABLE` + 檢查/補上 category / invoice_no 欄位。

## Request Flow

```
LINE/Discord 訊息
  → line_handler.py / discord_handler.py
    → core.process_text_message(msg)  # 文字指令路由
    → core.handle_image(bytes)        # 圖片記帳
      → gemini.py (AI 呼叫)
      → database → models (ORM 寫入)
      → gemini.generate_persona_comment() (角色回應)
  ← 回覆訊息列表
```

```
網頁報表
  → /report?token=xxx (auth.validate_report_token)
    → templates/report.html (前端 SPA)
      → /api/report/* (報表資料 API，require_token)
      → /api/record/* (CRUD API，require_token)
```

## Scheduled Jobs (APScheduler)

| Job | Schedule | Function |
|-----|----------|----------|
| weekly_categorize | 每週日 00:00 (Asia/Taipei) | categorize.run_weekly_categorization() |
| daily_recurring | 每日 00:05 | recurring.run_daily_recurring() |
| daily_invoice_sync | 每日 21:00 | `_daily_invoice_with_notify()` — 抓今天+昨天 + 通知 Discord `#🧾-發票通知`（含「新增明細」second embed，逐筆列日期/品名/金額，超過 3900 字自動截斷） |
| monthly_summary | 每月 1 號 09:00 | `notify_monthly_summary()` — 上月結算 embed 推到 `#📊-報表查詢` |

## Core Logic: Text Command Routing (core.py)

`process_text_message(msg)` 依序匹配：
1. `說明`/`help` → HELP_TEXT
2. `分類` → run_weekly_categorization()
3. `報表` → generate_report_token() → 回傳連結
4. `固定 支出/收入 品名 金額 日期` → handle_add_recurring()
5. `固定清單` → handle_list_recurring()
6. `取消固定 ID` → handle_delete_recurring()
7. `查詢` → handle_query_monthly()
8. `最近` → handle_query_recent()
9. `刪除收入 ID` → handle_delete_income()
10. `刪除 ID` → handle_delete_expense()
11. `修改收入 ID 品名 金額` → handle_update_income()
12. `修改 ID 品名 金額` → handle_update_expense()
13. `抓發票` / `抓發票 N` → handle_fetch_invoices(days)
14. fallback: handle_record_text() → regex 解析 `品名 金額` 記帳

## Key Patterns

- **SessionLocal pattern**: 所有 DB 操作用 `db = SessionLocal()` + try/finally/db.close()
- **LINE handler**: 同步函式，純文字回覆（`line_bot_api.reply_message`），呼叫 `core.handle_*()` 取 `list[str]`
- **Discord handler**: 非同步，slash commands + embeds，呼叫 `core.*_data()` 取結構化 dict 後組 embed
- **Auth**: in-memory token store (dict)，30 分鐘過期，非持久化
- **Gemini 呼叫**: 直接用 urllib.request（非 SDK），手動組 JSON payload
- **雙介面 API 設計**:
  - LINE 用 `core.handle_*()` 系列 → 回 `list[str]`（既有純文字風格）
  - Discord 用 `core.*_data()` 系列 → 回 `dict` / `list[dict]`（給 embed builder 組卡片）

## Discord Bot Architecture (discord_handler.py)

- **MoneyBot(discord.Client)** + `app_commands.CommandTree`
- 14 個 slash commands 全用中文名稱（`/記帳`, `/查詢`, `/最近` 等）
- 每個 command callback 流程：(1) `await ix.response.defer()` 必要時、(2) 呼叫 `core.*_data()`、(3) 用對應 embed builder 組卡片、(4) `ix.followup.send(embeds=...)`
- 慢 commands（`/記帳`, `/收入`, `/分類`, `/抓發票`）必 defer 避免 3 秒超時
- 配色：支出 `#E74C3C` / 收入 `#2ECC71` / 查詢 `#3498DB` / 木須龍 `#9B59B6` / 警告 `#F1C40F`
- 圖片附件走 `on_message`（slash 不適合接拖拉檔案）
- **Sync→Async 橋接**：`set_bot()`/`_post_embeds_sync()` 讓 APScheduler 排程（同步 thread）能投遞 embeds 到 Discord。原理：把 coroutine 用 `asyncio.run_coroutine_threadsafe(coro, bot.loop)` 排到 bot 的 event loop
- **頻道結構**（由一次性 setup 腳本建立）：
  - `📊 記帳機器人` (category)
    - `#📝-記帳` — slash commands 主場
    - `#📊-報表查詢` — 月結自動 post 到此
    - `#🧾-發票通知` — 每日抓發票結果自動 post 到此
  - 各頻道頂部釘選歡迎卡片（含 banner 圖、用途說明）
  - 對應 channel ID 存在 `.env`：`DISCORD_RECORD_CHANNEL_ID` / `DISCORD_REPORT_CHANNEL_ID` / `DISCORD_INVOICE_CHANNEL_ID`

## Environment Variables

LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, DATABASE_URL, GEMINI_API_KEY, MODEL_NAME, DISCORD_BOT_TOKEN (optional), DISCORD_INVOICE_CHANNEL_ID (optional), DISCORD_REPORT_CHANNEL_ID (optional), DISCORD_RECORD_CHANNEL_ID (optional), NGROK_AUTHTOKEN, EINVOICE_PHONE_1, EINVOICE_PASSWORD_1, EINVOICE_PHONE_2 (optional), EINVOICE_PASSWORD_2 (optional)
