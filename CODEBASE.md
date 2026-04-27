# Codebase Index (AI Quick Reference)

> 供 AI 快速理解專案結構，每次 commit 時更新。
> Last updated: 2026-04-25

## Stack

Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL 15 / Gemini API / LINE Bot SDK 2.4.3 / discord.py / APScheduler / Playwright (Chromium) / ECharts 5 / Docker Compose + ngrok

## File Map

```
.
├── main.py              # 入口：FastAPI app 建立、DB 初始化、APScheduler 排程、Discord Bot 啟動
├── core.py              # 核心業務邏輯：所有文字指令解析(regex)與處理函式、圖片記帳、訊息路由
├── line_handler.py      # LINE Bot：webhook /callback、文字/圖片訊息事件處理
├── discord_handler.py   # Discord Bot：MoneyBot(discord.Client)、文字/圖片訊息處理
├── gemini.py            # Gemini API 封裝：gemini_text()、gemini_image()、generate_persona_comment()
├── database.py          # SQLAlchemy engine/SessionLocal/Base 建立（讀 DATABASE_URL）
├── models.py            # ORM 模型：Transaction(支出)、Income(收入)、RecurringRecord(固定收支)
├── categorize.py        # AI 分類：run_weekly_categorization() 批次分類未分類帳目
├── recurring.py         # 固定收支：run_daily_recurring() 每日自動寫入到期項目
├── auth.py              # Token 驗證：generate_report_token()、validate_report_token()、require_token dependency
├── einvoice.py          # 財政部電子發票同步：Playwright 登入 → CAPTCHA(Gemini) → 抓發票 → 寫 transactions
├── persona.md           # AI 角色設定：木須龍(台灣配音風格)，記帳後生成角色回應
├── requirements.txt     # Python 依賴
├── Dockerfile           # python:3.11-slim，pip install → uvicorn 啟動
├── docker-compose.yml   # 三個服務：app(8000)、db(PostgreSQL)、ngrok(tunnel)
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
| daily_invoice_sync | 每日 06:00 | einvoice.sync_invoices() — 抓今天的發票 |

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
- **LINE handler**: 同步函式，用 `line_bot_api.reply_message()` 回覆
- **Discord handler**: 非同步，用 `message.channel.send()` 回覆
- **Auth**: in-memory token store (dict)，30 分鐘過期，非持久化
- **Gemini 呼叫**: 直接用 urllib.request（非 SDK），手動組 JSON payload
- **回覆格式**: core 函式回傳 `list[str]`，各平台 handler 負責逐條發送

## Environment Variables

LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, DATABASE_URL, GEMINI_API_KEY, MODEL_NAME, DISCORD_BOT_TOKEN (optional), NGROK_AUTHTOKEN, EINVOICE_PHONE_1, EINVOICE_PASSWORD_1, EINVOICE_PHONE_2 (optional), EINVOICE_PASSWORD_2 (optional)
