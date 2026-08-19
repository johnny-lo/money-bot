# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 專案文件是中文的，回覆與 commit 訊息也用繁體中文。

## 動手前必讀

1. **`AGENTS.md`** — 踩過的坑 + 根因 + 解法（部署快取、import 崩潰、DB migration、PWA 佈局、Discord、測試姿態）。
   **這是本 repo 最重要的檔案，改任何東西前先讀。**
2. **`CODEBASE.md`** — 逐檔案地圖 + DB schema + 排程表 + 環境變數清單。要找「哪個檔在做什麼」看這裡。
3. **`README.md`** — 功能與指令總覽（LINE 文字指令 / Discord slash commands）。

## 執行環境

**一切跑在 Docker，host 沒有 python。** 三個容器：`money-bot`（FastAPI + Discord Bot）、
`money-db`（Postgres，無對外 port）、`money-tunnel`（ngrok）。專案目錄 live-mount 成 `/app`
→ 改完 Python 原始碼 container 立刻看得到，**不用 rebuild image**。

```bash
# 全套測試（427 個，約 3 秒）
docker exec -w /app money-bot python -m pytest tests/ -q

# 單檔 / 單一測試
docker exec -w /app money-bot python -m pytest tests/test_food_repo.py -v
docker exec -w /app money-bot python -m pytest tests/test_food_repo.py -k 台灣收斂 -v

# import 預檢（重啟前必做；import 崩潰 = webhook + bot 全掛）
docker exec -w /app money-bot python -c "import main" && echo OK

# 後端改 → 重啟（不是 docker compose up，那是改 env 才用）
docker restart money-bot

# 前端改 → build（host 跑得動 npm；live-mount 直接生效，免重啟）
npm run build --prefix frontend

# 起停整套（改 .env 才需要）
docker compose up -d --build
```

重啟後 server ready 要等 30–90 秒（開機會跑 Playwright 發票同步阻塞），
這段 curl 回 `HTTP 000` 是正常的——輪詢 log 等 `Application startup complete`，別用固定 sleep
（輪詢腳本見 `AGENTS.md` §1）。

驗 API 要用 **DB 裡的 device token**（`X-Device-Token` header），不能用 `auth.generate_report_token()`
——那是伺服器行程的記憶體，`docker exec` 是另一個行程鑄不出來（取法見 `AGENTS.md` §3）。

## 架構大圖

### 三個介面、一組核心

```
LINE 文字/圖片 ─→ line_handler.py  ─┐
Discord 訊息   ─→ discordbot/bot.py ─┼→ core.py ──→ models.py / database.py
手機 PWA       ─→ routes/*.py       ─┘              gemini.py / codex_cli.py
```

- **雙介面 API 慣例（core.py 的骨架）**：LINE 走 `core.handle_*()` → 回 `list[str]` 純文字；
  Discord 走 `core.*_data()` → 回 `dict`，再由 `discordbot/embeds.py` 組卡片。加功能時照這個分裂維持。
- **一個真相、多個薄客戶端**：每個模組的 `repo.py` 是唯一 DB 存取層，AI / Discord / PWA 三邊都呼叫同一組
  函式，不各寫一套。例：`video/repo.py`、`food/repo.py`。

### 功能模組的標準分層（食譜/美食/影片都長一樣）

```
links.py    純函式：URL 偵測 + 平台分類（無 I/O）
extract.py  外部資料 → 欄位 JSON（yt-dlp / og fetch / Gemini Vision / codex）
repo.py     DB CRUD —— upsert 是唯一寫入咽喉點，正規化與守衛都放這裡
ingest.py   orchestrator：extract → 正規化 → upsert → 事後補強（best-effort）
```

**加新模組前先找形狀最像的既有模組整條讀懂，照它的分層做**（`AGENTS.md` 頭號鐵則）。

### 其他關鍵結構

- **AI 分工**：影像（拍照記帳、發票 CAPTCHA、木須龍即時評論）走 `gemini.py`（計費 API）；
  文字（帳目分類、週/月報評語、店名/菜名抽取）走 `codex_cli.py`（shell 呼叫容器內的 `codex` CLI，
  ChatGPT 訂閱制，不計費）。新增文字生成一律用 codex。
- **排程**：`main.py` 的 APScheduler（Asia/Taipei）——每日固定收支、週一~六 21:00 發票補拓、
  週日 21:00 一條龍（補拓→分類→週報，每月第一個週日多推月結）、開機後 3 分鐘補拓。
  排程是同步 thread，要推 Discord 得經 `discordbot/bridge.py` 的 sync→async 橋接。
- **認證兩層**（`auth.py`）：報表短效 token（30 分鐘、in-memory）↔ PWA 長效 device token（DB）。
  `routes/device.py` 只收短效換發長效——洩漏的 device token 無法自我繁殖。
- **前端**：`frontend/` 是 React + Vite + vite-plugin-pwa 的手機 PWA，build 產物 `frontend/dist`
  由 `main.py` 掛在 `/m`（**被 gitignore，只 commit `frontend/src`**）。四個 tab：美食 / 消費 / 食譜 / 歷史。
  `main.py` 的 `pwa_cache_headers` middleware 負責殼 `no-cache` + assets `immutable`，
  **動到它等於動到「手機拿不拿得到新版」**。

### DB migration 規則

`main.py` 的 `Base.metadata.create_all` **只建新表、不改既有表結構**：

- **新表** → 開機自動建，免 migration。
- **既有表加欄位/FK** → 要手動 `ALTER`，照 `main.py:35-84` 的 inspector + `ALTER TABLE` 寫法補一段。
  那段 try 會吞例外 → 重啟後 `docker logs money-bot | grep -E '✅|⚠️'` 確認真的加成功。

## 測試姿態

純單元測試，**不連 DB、不出網**：model 用 `__table__.columns` introspection 驗欄位；
邏輯用 `FakeSession` + monkeypatch 驗寫入契約。TDD 瞄準純函式（parser、JSON 解析、正規化、分類）；
repo/route/handler 的 glue 沒有單元測試，靠 curl / Discord / 直接在 container 內呼叫 orchestrator 的
smoke 驗。**手機 CSS 算繪沒有自動化測試**，改完要使用者親眼確認才算完成。

⚠️ smoke 用真連結跑 `ingest.from_url(...)` 會**真的寫進情侶共用的正式 DB** → 挑可刪的資料並主動告知使用者。

## 專案鐵律

1. **每個功能 commit 必更新 `README.md` + `CODEBASE.md`**（純設計/計畫文件 commit 可豁免）。
2. **先全局，後新增**：加功能前先讀 codebase 想全局 → 想怎麼接 → 才動手。順序不能反。
3. **重啟前 / 宣稱完成前跑一次 `AGENTS.md` §9 檢查清單**（import 預檢 → 全套測試 → 等 startup complete
   → curl smoke → 文件更新）。拿得出證據才說「好了」。
4. 新踩到的坑往 `AGENTS.md` 加一條（根因 + 解法 + 教訓），別讓下一輪重踩。
