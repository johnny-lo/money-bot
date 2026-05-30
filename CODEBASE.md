# Codebase Index (AI Quick Reference)

> 供 AI 快速理解專案結構，每次 commit 時更新。
> Last updated: 2026-05-11

## Stack

Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL 15 / Gemini API / LINE Bot SDK 2.4.3 / discord.py / APScheduler / Playwright (Chromium) / ECharts 5 / Docker Compose + ngrok

## File Map

```
.
├── main.py              # 入口：FastAPI app 建立、DB 初始化、APScheduler 排程、Discord Bot 啟動
├── core.py              # 核心業務邏輯：文字指令解析/處理、圖片記帳、訊息路由 + Data API（Discord embeds 用）
├── line_handler.py      # LINE Bot：webhook /callback、文字/圖片訊息事件處理（純文字介面）
├── discord_handler.py   # Discord Bot：21 個 Slash Commands + Embeds、圖片附件 on_message 處理
├── gemini.py            # Gemini API 封裝：gemini_image()（影像辨識：拍照記帳、CAPTCHA，用 MODEL_NAME）、gemini_text()（保留作後備）、generate_persona_comment()（木須龍記帳評論，走 Gemini 文字）
├── codex_cli.py         # codex_text(prompt)：shell 出去呼叫本機 `codex exec`（ChatGPT 訂閱制，預設 gpt-5.5），用 --output-last-message 取乾淨輸出。供「分類 + 週/月報評語」的文字生成用，取代計費的 Gemini 文字 API（CODEX_MODEL env 可覆蓋模型）
├── database.py          # SQLAlchemy engine/SessionLocal/Base 建立（讀 DATABASE_URL）
├── models.py            # ORM 模型：Transaction(支出)、Income(收入)、RecurringRecord(固定收支)
├── categorize.py        # AI 分類（走 codex_text / 訂閱制）：CATEGORIES(13 細類)/CATEGORY_GROUPS(細→大組)/GROUP_ORDER、run_weekly_categorization()(只處理 NULL)、run_full_recategorization()(清掉全部重跑)、category_group()。AI 分批 50 筆送，避免單次 prompt 太長
├── report_helpers.py    # 報表純函式（無 DB / 無網路）：compare(對比)、top_n_expenses、detect_anomalies、sparkline/daily_heatmap、savings_rate、budget_status、日期工具(week_range/month_range/is_first_sunday 等)。全部由 tests/test_report_helpers.py 覆蓋（49 個測試）
├── tests/               # pytest 測試。跑法：`docker compose exec app pytest tests/ -v`
├── recurring.py         # 固定收支：run_daily_recurring() 每日自動寫入到期項目
├── auth.py              # Token 驗證：generate_report_token()、validate_report_token()、require_token dependency
├── einvoice.py          # 財政部電子發票同步：Playwright 登入 → CAPTCHA(Gemini) → 抓發票 → 寫 transactions。`sync_invoices()` 回傳 `{"summary": str, "new_items": list[dict]}`，支援多組載具（EINVOICE_PHONE_1/2 + PASSWORD_1/2）
├── persona.md           # AI 角色設定：木須龍(台灣配音風格)，記帳後生成角色回應
├── resource/            # Discord 頻道歡迎 banner 圖（手動放入，由 _setup_discord 一次性上傳；已 .gitignore 不入版本控制）
├── food/
│   ├── __init__.py
│   ├── regions.py       # 地名正規化（純函式）：canon()、region_matches()、parse_address_components()
│   ├── places.py        # Google Places (New) 整合：search_text(query)→dict|None、maps_url(place_id)→str、fetch_reviews(place_id)→list、caution_for_place_id(place_id)→str(低星評論 AI 雷點摘要)
│   ├── links.py         # URL 偵測 + 平台判斷（純函式，無 I/O）：find_urls()、classify_platform()(youtube/instagram/threads/tiktok/facebook/gmaps/other,子網域邊界比對防釣魚)、strip_urls()、detect_links()、first_link()
│   ├── extract.py       # 截圖/文字/連結 → 欄位 JSON：parse_extracted_json()(純函式)、from_image()(Gemini Vision)、from_text()(codex)、parse_video_id()(YouTube 11 碼 ID,純函式)、gmaps_place_name()(Google Maps URL path 解店名,純函式)、parse_og()(HTML body 抽 og:title/description,純函式)、from_url(url, platform)(I/O wrapper,yt-dlp 主 + og fetch 備援,Maps follow redirect→gmaps_place_name；og fetch 用 facebookexternalhit UA 才拿得到 Threads/Meta 平台 og 標籤)、deep_extract_via_codex()(全 access codex CLI 深度振查,看圖+搜尋交叉驗證,前兩層抽不到店名才動用)。三個 prompt(_TEXT_PROMPT/_IMAGE_PROMPT/_DEEP_PROMPT)精準區分 recommended_items(文中明確稱讚/必點/招牌的具體菜名,例:歐巴豬五花) vs cuisine_type(店家主要販售的料理類型,例:拉麵/咖啡/早午餐),避免把料理類別誤塞進推薦欄
│   ├── pending.py       # 需補件 in-memory 暫存(無 TTL,重啟丟失)：remember()/get()/consume()/clear()
│   ├── ingest.py        # orchestrator：extract → places → upsert → 事後雷點(best-effort)。回 (place|None, missing_reason)。`from_url(url, *, caption='')` 用 extract.from_url 抽 blob → codex from_text → 抽不到店名再 deep_extract_via_codex → _from_fields 入庫
│   ├── repo.py          # food_places 表 CRUD：upsert_place()、list_places(status)、set_visited()、to_dict()、set_message_id()、update_caution()、set_visited_by_message_id()
│   ├── map_data.py      # build_map_places(places)(純函式)：過濾無座標、整形地圖 marker JSON、status→visited、組 maps_url
│   └── recommend.py     # 推薦邏輯（純函式）：filter_for_recommendation()、sort_recent()、pick_random()
├── requirements.txt     # Python 依賴
├── Dockerfile           # python:3.11-slim，pip install → uvicorn 啟動
├── docker-compose.yml   # 三個服務：app(127.0.0.1:8000)、db(PostgreSQL，僅 docker network)、ngrok(127.0.0.1:4040 inspector + tunnel)
├── routes/
│   ├── __init__.py
│   ├── report.py        # 報表 API：/api/report/monthly|category|summary|ledger + /report 頁面
│   ├── record.py        # CRUD API：POST/PUT/DELETE /api/record（供網頁報表使用）
│   └── food_map.py      # 美食地圖：GET /food/map(HTML,自驗 token,注入 browser key/mapId) + GET /api/food/places(JSON,Depends token)
└── templates/
    ├── report.html      # 互動式報表 SPA：ECharts 圖表 + 流水帳 CRUD（純前端 JS）
    └── food_map.html    # 美食地圖頁：Google Maps JS、想去藍/去過綠 AdvancedMarker、點 pin InfoWindow(含雷點)、想去去過 toggle
```

## DB Schema

| Table | Columns | Notes |
|-------|---------|-------|
| `transactions` | id(PK), item(str), price(int), category(str?), invoice_no(str?), created_at(datetime) | 支出。invoice_no 是發票去重 key（einvoice 自動帶入；手動記帳為 NULL） |
| `incomes` | id(PK), item(str), amount(int), category(str?), created_at(datetime) | 收入 |
| `recurring_records` | id(PK), type("expense"/"income"), item, amount, category?, day_of_month(1-28), active(1/0), created_at | 固定收支 |
| `food_places` | id(PK), place_id(str?), name, address?, lat?, lng?, country?, city?, district?, cuisine_type?, recommended_items?, caution_summary?, status("想去"/"去過"), my_rating(int?), my_note?, source_url?, updated_at, created_at | 美食地圖（Phase 1A+） |

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

時區 `Asia/Taipei`。

| Job | Schedule | Function |
|-----|----------|----------|
| daily_recurring | 每日 00:05 | `recurring.run_daily_recurring()` |
| daily_invoice_sync | 週一 ~ 週六 21:00 | `_daily_invoice_with_notify()` — 抓今天+昨天 + 通知 Discord `#🧾-發票通知`（含「新增明細」second embed，逐筆列日期/品名/金額，超過 3900 字自動截斷） |
| weekly_pipeline | 週日 21:00 | `_weekly_pipeline()` — 一條龍：(1) 抓發票+通知 → (2) `run_weekly_categorization()` → (3) `notify_weekly_summary()` 週報。**每月第一個週日**（即 `day ≤ 7` 的週日）會額外串接 (4) `notify_monthly_summary()` 推上月完整月結 |

## Category Schema (categorize.py)

13 細類 → 6 大組對應，封閉清單（AI 必須從中選一）：

| 大組 | 細類 |
|---|---|
| 固定 | 居住水電、分期保險 |
| 交通 | 交通 |
| 飲食 | 三餐、聚餐、飲料零食、食材、超商 |
| 生活 | 日用品、醫療、服飾 |
| 娛樂 | 娛樂 |
| 其他 | 其他 |

- **居住水電** = 房租、管理費、電費、水費、瓦斯
- **分期保險** = 車貸、手機分期、其他貸款攤提、車險、人壽險、意外險
- **交通** = 加油、停車費、車輛保養、洗車、ETC、大眾運輸
- **三餐** = 正餐外食（單筆通常 ≤ 1500 元）
- **聚餐** = 大額餐廳消費、家人/朋友聚餐請客（單筆通常 > 1500 元）
- **超商** = 萊爾富/7-11/全家 等只看得到店名的發票
- 改規則：改 `CATEGORIES` + `CATEGORY_GROUPS` + `CATEGORIZE_RULES`，再呼叫 `run_full_recategorization()` 重跑歷史

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
- 21 個 slash commands 全用中文名稱（`/記帳`, `/查詢`, `/最近`, `/測試週報`, `/測試月報`, `/美食新增`, `/美食推薦`, `/美食清單`, `/去過`, `/美食地圖` 等）
- 每個 command callback 流程：(1) `await ix.response.defer()` 必要時、(2) 呼叫 `core.*_data()`、(3) 用對應 embed builder 組卡片、(4) `ix.followup.send(embeds=...)`
- 慢 commands（`/記帳`, `/收入`, `/分類`, `/抓發票`）必 defer 避免 3 秒超時
- 配色：支出 `#E74C3C` / 收入 `#2ECC71` / 查詢 `#3498DB` / 木須龍 `#9B59B6` / 警告 `#F1C40F`
- 圖片附件走 `on_message`，依頻道分流：`FOOD_INGEST_CHANNEL_ID` → `_handle_food_message()`（截圖/文字 ingest、reply 補件）；`DISCORD_RECORD_CHANNEL_ID` → `_do_image_recording()`（圖片記帳）；**未設 RECORD 頻道則退回「任意頻道圖片記帳」舊行為**；其他頻道圖片回指引（`_HINT_DEBOUNCE` 30 分鐘防洗版）
- `on_raw_reaction_add`：在 `#美食輸入` 對店家卡片按 ✅ → `set_visited_by_message_id()` 標去過 + 追問評分/心得
- **Sync→Async 橋接**：`set_bot()`/`_post_embeds_sync()` 讓 APScheduler 排程（同步 thread）能投遞 embeds 到 Discord。原理：把 coroutine 用 `asyncio.run_coroutine_threadsafe(coro, bot.loop)` 排到 bot 的 event loop
- **頻道結構**（由一次性 setup 腳本建立）：
  - `📊 記帳機器人` (category)
    - `#📝-記帳` — slash commands 主場
    - `#📊-報表查詢` — 月結自動 post 到此
    - `#🧾-發票通知` — 每日抓發票結果自動 post 到此
  - 各頻道頂部釘選歡迎卡片（含 banner 圖、用途說明）
  - 對應 channel ID 存在 `.env`：`DISCORD_RECORD_CHANNEL_ID` / `DISCORD_REPORT_CHANNEL_ID` / `DISCORD_INVOICE_CHANNEL_ID`
- **週報 (`notify_weekly_summary`)** — 本週（週一→週日）embed 欄位：三格頭(收/支/淨) → vs 上週對比 → 大組分布 → 細類分布(前 8) → Top 3 單筆 → 每日支出迷你長條 → 異常分類(近 4 週均值+50%) → AI 評語
- **月結 (`notify_monthly_summary`)** — 上月 embed 欄位：三格頭 → vs 上上月對比 → 儲蓄率 → 預算狀態(`MONTHLY_BUDGET`) → 大組 → 細類(前 8) → Top 3 → 近 6 月 sparkline → 異常分類(近 4 月均值+50%) → AI 評語
- **AI 評語**：兩種報表共用 `_generate_ai_comment()`，走 `codex_cli.codex_text()`（ChatGPT 訂閱制，預設 gpt-5.5，不再用計費 Gemini，免 429 配額）+ persona.md 木須龍。會餵入報表已算好的 vs 上期對比 / 儲蓄率（月）/ 異常暴增分類 / 單筆 Top 3，要求講出具體數字與可執行建議；prompt 依 `period_kind` 分流（週報 2–3 句聚焦本週、月報 3–4 句講趨勢+下月行動）。失敗時欄位會顯示「⚠️ AI 評語生成失敗：{錯誤訊息}」，embed 照樣推。註：木須龍「記帳當下」評論（generate_persona_comment）仍走 Gemini，只有報表評語與分類改用 codex
- **手動測試**：在 Discord 用 `/測試週報` / `/測試月報` 立即觸發推送（**必須在 bot 主進程內呼叫**，因為 `_bot_instance` 是 module 級狀態；從 `docker compose exec` 開的子進程裡呼叫 `notify_*()` 會靜默失敗）
- **DB 查詢輔助** `_query_period(start, end)` 一次撈完一段期間需要的所有彙總（總額/分類/Top N/每日金額），週報跟月報共用

## Environment Variables

LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, DATABASE_URL, GEMINI_API_KEY, MODEL_NAME, CODEX_MODEL (optional, 留空=用 codex 預設 gpt-5.5), MONTHLY_BUDGET (optional, 0/不設=不顯示預算進度), DISCORD_BOT_TOKEN (optional), DISCORD_INVOICE_CHANNEL_ID (optional), DISCORD_REPORT_CHANNEL_ID (optional), DISCORD_RECORD_CHANNEL_ID (optional), NGROK_AUTHTOKEN, EINVOICE_PHONE_1, EINVOICE_PASSWORD_1, EINVOICE_PHONE_2 (optional), EINVOICE_PASSWORD_2 (optional), GOOGLE_PLACES_SERVER_KEY (美食地圖；後端 Places API New 用), FOOD_INGEST_CHANNEL_ID (美食地圖；#美食輸入 頻道), GOOGLE_MAPS_BROWSER_KEY (美食地圖 Phase 2；前端 Maps JS,限 ngrok referrer), GOOGLE_MAPS_MAP_ID (美食地圖 Phase 2；AdvancedMarker 必需,未申請填 DEMO_MAP_ID)

> codex 整合：`codex` CLI 裝在 app 映像內（Dockerfile 用 `npm install -g @openai/codex`，**非獨立 container**），登入憑證以 `docker-compose.yml` 把主機 `${HOME}/.codex` 掛到容器 `/root/.codex`（rw，讓 ChatGPT 訂閱 token 自動刷新可寫回）。`auth_mode=chatgpt`=訂閱制，不走單次計費 API。

> 注意：channel ID + EINVOICE 系列原本在 `.env` 但沒寫進 `docker-compose.yml` 的 `environment:` block，導致 container 內部 `os.getenv()` 拿不到 → 排程通知都會在 `if not chan_id: return` 靜默退出。已於 2026-05-11 修正。

## 規劃中模組（Specs）

- **美食地圖模組**（**Phase 1A + 1B + 2 + 3 已實作**）：
  - Phase 1A（slash）：`/美食新增`、`/美食推薦`（含🎲隨機）、`/美食清單`、`/去過`，手動建清單 + 縣市/國家推薦
  - Phase 1B（自動）：`#美食輸入` 頻道丟截圖/文字 → `food.ingest`（extract → Places 正規化 → upsert → 低星負評 AI 雷點摘要 best-effort）→ 卡片；抽不到走 `food.pending` reply 補件；✅ 反應標去過
  - Phase 2（地圖網頁）：`/美食地圖` → token 連結 → `routes/food_map.py` + `templates/food_map.html`，Google Maps JS、想去藍/去過綠 AdvancedMarker、點 pin InfoWindow（含雷點）、想去/去過 toggle。`food.map_data.build_map_places` 整形、過濾無座標。browser key 限 ngrok referrer
  - Phase 3（連結來源）：`#美食輸入` 貼 IG/YouTube/TikTok/Threads/Facebook/Google Maps/一般網站連結 → `food.links` 偵測 + 平台分類 → `food.extract.from_url` 抽 blob（**yt-dlp `--skip-download` 主力**抽 caption/title/description；Threads/一般網站走 og fetch + `facebookexternalhit` UA；Google Maps follow redirect → 直接解 URL path 店名）→ codex `from_text` 解店名/地區 → 抽不到再 `deep_extract_via_codex`（全 access、看圖+搜尋交叉驗證）→ `_from_fields` 入庫。`discord_handler._handle_food_message` 在純文字 ingest **之前**插入連結分流，多連結用 `asyncio.gather` + `asyncio.to_thread` **平行處理一次多家入庫**；抽不到店名（常見於 Threads/FB 店名在圖不在文字）→ 走 `pending` 補件卡（reply 補店名最快）
  - 設計見 `docs/superpowers/specs/2026-05-23-food-map-module-design.md`
  - **關鍵接合點**：`on_message` 依 `FOOD_INGEST_CHANNEL_ID` / `DISCORD_RECORD_CHANNEL_ID` 分流（後者未設則退回舊的任意頻道記帳），避免美食截圖被「拍照記帳」誤記成支出
