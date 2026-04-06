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
  - 流水帳明細（含新增/編輯/刪除功能）

### AI 功能
- **Gemini 圖片辨識** — 拍照自動解析消費明細
- **AI 自動分類** — 每週日 00:00 自動將未分類帳目分類（也可手動觸發 `分類`）
- **AI 角色回應** — 記帳後由「木須龍」角色（台灣配音風格）給出有趣評論

## 技術架構

| 層級 | 技術 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 資料庫 | PostgreSQL 15 (SQLAlchemy ORM) |
| AI | Google Gemini API (文字 + 多模態) |
| 訊息平台 | LINE Bot SDK 2.4.3 / discord.py |
| 排程 | APScheduler (背景排程) |
| 前端報表 | ECharts 5 (純 HTML/JS) |
| 部署 | Docker Compose (app + PostgreSQL + ngrok) |

## 環境變數 (.env)

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token |
| `DATABASE_URL` | PostgreSQL 連線字串 |
| `GEMINI_API_KEY` | Google Gemini API Key |
| `MODEL_NAME` | Gemini 模型名稱 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token（選填，未設定則跳過） |
| `NGROK_AUTHTOKEN` | ngrok 認證 Token |

## 快速啟動

```bash
# 1. 設定環境變數
cp .env.example .env  # 填入各項 API Key

# 2. 啟動所有服務
docker compose up -d --build

# 3. 確認服務狀態
docker compose logs -f app
```

服務啟動後：
- FastAPI 跑在 `http://localhost:8000`
- ngrok 管理面板在 `http://localhost:4040`
- LINE Webhook URL: `https://<your-ngrok-domain>/callback`

## 指令一覽

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
| `固定 支出/收入 品名 金額 日期` | 建立固定收支 |
| `固定清單` | 查看固定項目 |
| `取消固定 ID` | 取消固定項目 |
| `說明` / `help` | 顯示指令說明 |
| 傳送照片 | AI 辨識發票/明細 |
