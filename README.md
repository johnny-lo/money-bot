# Money Bot - LINE / Discord 記帳機器人

一個以 **FastAPI** 為後端的多平台記帳機器人，同時支援 LINE Bot 與 Discord Bot，搭配 **Gemini AI** 進行圖片辨識記帳與自動分類，並提供互動式網頁報表。

## 功能總覽

### 記帳
- **文字記帳** — 輸入 `午餐 150` 即可記錄支出，支援多行批次輸入
- **收入記錄** — `收入 薪水 50000`
- **拍照記帳** — 傳送發票/明細照片，AI 自動辨識品項與金額
- **修改/刪除** — `修改 ID 新品名 新金額`、`刪除 ID`

### 固定收支
- **建立** — `固定 支出 房租 15000 1`（每月 1 號自動記入）
- **清單** — `固定清單`
- **取消** — `取消固定 ID`

### 查詢與報表
- **本月結算** — `查詢`（總收入/總支出/淨支出）
- **最近紀錄** — `最近`（最近 5 筆）
- **互動式網頁報表** — `報表`（產生 30 分鐘有效的一次性連結）
  - 每日/每月收支趨勢折線圖
  - 支出分類圓餅圖
  - 近 6 個月柱狀圖對比
  - 流水帳明細（含新增/編輯/刪除功能、收支類型 + 分類雙重下拉篩選）

### 自動報表
- **週報**（每週日 21:00 推 Discord `#📊-報表查詢`）：本週收支三格頭、與上週對比、大組分布、細類分布、單筆最大 Top 3、每日支出迷你長條圖、異常分類偵測、AI 評語
- **月報**（每月第一個週日接在週報後）：上月收支三格頭、與上上月對比、儲蓄率、預算狀態（需設 `MONTHLY_BUDGET`）、大組分布、細類分布、Top 3、近 6 月走勢迷你折線、異常分類偵測、AI 評語

### AI 功能
- **Gemini 圖片辨識** — 拍照自動解析消費明細
- **AI 自動分類** — 每週日 21:00 自動將未分類帳目分類（也可手動觸發 `分類`）。13 細類分 6 大組：
  - **固定**：居住水電 / 分期保險
  - **交通**：交通
  - **飲食**：三餐 / 聚餐 / 飲料零食 / 食材 / 超商
  - **生活**：日用品 / 醫療 / 服飾
  - **娛樂**：娛樂
  - **其他**：其他
- **AI 角色回應** — 記帳後由「木須龍」角色（台灣配音風格）給出有趣評論
- **AI 週評語** — 週日 21:00 週報用更強的 Gemini 模型（`WEEKLY_MODEL`，預設 `gemini-pro-latest`）生成本週理財評語

### 電子發票自動同步
- **週一 ~ 週六 21:00 自動抓**手機條碼載具當日 + 昨日發票（避免錯過 21:00 後新開立的），逐筆解析品名/金額寫入支出，並把當次新增明細以 embed 推到 Discord `#🧾-發票通知`
- **週日 21:00** 順序執行「抓發票 → AI 分類 → 週報卡片」一條龍 pipeline，週報推到 `#📊-報表查詢`
- **手動觸發** — `抓發票`（抓今天）、`抓發票 7`（近 7 天）
- **CAPTCHA 自動破解** — 用 Gemini Vision 辨識財政部圖形驗證碼
- **去重機制** — 以發票號碼為 key，重跑不會重複寫入
- **品項代號處理** — 純數字代號（如藥局商品 SKU）會自動加上賣方名前綴方便辨識

## 技術架構

| 層級 | 技術 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 資料庫 | PostgreSQL 15 (SQLAlchemy ORM) |
| AI | Google Gemini API (文字 + 多模態) |
| 訊息平台 | LINE Bot SDK 2.4.3 / discord.py |
| 排程 | APScheduler (背景排程) |
| 爬蟲 | Playwright + Chromium (財政部電子發票) |
| 前端報表 | ECharts 5 (純 HTML/JS) |
| 部署 | Docker Compose (app + PostgreSQL + ngrok) |

## 環境變數 (.env)

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token |
| `DATABASE_URL` | PostgreSQL 連線字串 |
| `GEMINI_API_KEY` | Google Gemini API Key |
| `MODEL_NAME` | Gemini 模型名稱（記帳/分類/角色回應） |
| `WEEKLY_MODEL` | 週/月評語用的強模型（選填，預設 `gemini-pro-latest`） |
| `MONTHLY_BUDGET` | 月度預算金額（選填，0 = 不顯示預算進度）|
| `DISCORD_BOT_TOKEN` | Discord Bot Token（選填，未設定則跳過） |
| `DISCORD_INVOICE_CHANNEL_ID` | 發票通知頻道 ID（選填） |
| `DISCORD_REPORT_CHANNEL_ID` | 週報 / 月結通知頻道 ID（選填） |
| `DISCORD_RECORD_CHANNEL_ID` | 記帳主頻道 ID（選填，預留） |
| `NGROK_AUTHTOKEN` | ngrok 認證 Token |
| `EINVOICE_PHONE_1` | 第一組載具：財政部電子發票會員手機號碼 |
| `EINVOICE_PASSWORD_1` | 第一組載具：驗證碼（密碼） |
| `EINVOICE_PHONE_2` | 第二組載具（選填） |
| `EINVOICE_PASSWORD_2` | 第二組載具密碼（選填） |

## 快速啟動

```bash
# 1. 設定環境變數
cp .env.example .env  # 填入各項 API Key

# 2. 啟動所有服務
docker compose up -d --build

# 3. 確認服務狀態
docker compose logs -f app

# 4. 跑單元測試（report_helpers 純函式）
docker compose exec app pytest tests/ -v
```

服務啟動後：
- FastAPI 跑在 `http://localhost:8000`（loopback only，不對外）
- ngrok 管理面板在 `http://localhost:4040`（loopback only，不對外）
- LINE Webhook URL: `https://<your-ngrok-domain>/callback`

## 指令一覽

### LINE（純文字）
| 指令 | 說明 |
|------|------|
| `午餐 150` | 記錄支出 |
| `收入 薪水 50000` | 記錄收入 |
| `查詢` | 本月收支總覽 |
| `最近` | 最近 5 筆紀錄 |
| `報表` | 互動式圖表報表 |
| `修改 ID 新品名 新金額` | 修改支出 |
| `修改收入 ID 新品名 新金額` | 修改收入 |
| `刪除 ID` | 刪除支出 |
| `刪除收入 ID` | 刪除收入 |
| `分類` | 手動觸發 AI 分類 |
| `抓發票` / `抓發票 7` | 手動抓發票 |
| `固定 支出/收入 品名 金額 日期` | 建立固定收支 |
| `固定清單` / `取消固定 ID` | 管理固定項目 |
| `說明` / `help` | 顯示指令說明 |
| 傳送照片 | AI 辨識發票/明細 |

### Discord（Slash Commands + Embeds + 多頻道）
所有回覆用彩色 embed 卡片（💸 支出紅、💰 收入綠、🔍 查詢藍、🐉 木須龍紫）。

**頻道結構**（一次性 setup 腳本建立，含木須龍主題 banner 圖）：
- `#📝-記帳` — slash commands 主場
- `#📊-報表查詢` — 每週日 21:00 自動 post 週報；每月第一個週日同時連推上月完整月結
- `#🧾-發票通知` — 週一 ~ 週六 21:00 抓完發票自動 post 結果（週日歸週報 pipeline）

| Slash | 說明 |
|-------|------|
| `/記帳 品名 金額` | 記支出 |
| `/收入 品名 金額` | 記收入 |
| `/查詢` | 本月結算（含分類占比） |
| `/最近 [筆數]` | 最近紀錄（1-10） |
| `/報表` | 互動式網頁報表 |
| `/修改 編號 品名 金額` | 修改支出 |
| `/修改收入 編號 品名 金額` | 修改收入 |
| `/刪除 編號` / `/刪除收入 編號` | 刪除 |
| `/固定支出` / `/固定收入` | 新增固定項目 |
| `/固定清單` / `/取消固定` | 管理固定項目 |
| `/分類` / `/抓發票 [天數]` | AI 分類 / 同步發票 |
| `/說明` | 顯示所有指令 |
| 拖曳圖片 | AI 辨識發票/明細 |
