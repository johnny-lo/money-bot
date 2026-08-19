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

### 美食地圖
- **手動新增**（Phase 1A，slash）：`/美食新增 店名 [區域] [推薦品項]` → 查 Google Places 正規化 → 存「想去」
- **截圖/文字自動記**（Phase 1B）：在 `#美食輸入` 頻道丟**截圖**或打**文字**（如「鼎泰豐 信義」）→ bot 自動抽店名、查 Google、入庫並貼卡片（含 Google 低星負評 AI「雷點摘要」best-effort）
- **需補件**：抽不到完整資訊 → 貼 ⚠️ 卡片，**reply 該卡片**補上店名/地址即可接回（補件記憶體於 bot 重啟後失效，重貼即可）
- **標去過**：對店家卡片按 ✅ → 立即標「去過」（之後可用 `/去過 編號 [評分] [心得]` 補評分/心得）
- **推薦**：`/美食推薦 <縣市/鄉鎮市區/國家>` 列想去清單 + 🎲 隨機挑一家；`/美食清單 [想去/去過]`
- **附近有什麼**（PWA 預設畫面）：進美食頁先定位，拉範圍滑桿（1/3/5/10/30 km，標註約略車程），看到**這個範圍內你的清單有哪些料理、各幾家**——Google Maps 只回答「X 在哪裡」，這裡回答「附近有哪些**已經被你篩選過**的選擇」。點料理磚塊才展開店家。沒給定位權限會自動退回清單模式並顯示提示，不會卡住。
- **分類顆粒度**：地區細到**鄉鎮市區**（桃園市中壢區 / 新竹縣竹北市 / 新竹縣竹東鎮），料理走**兩層**——12 個受控大類（日式/韓式/中式/台式/東南亞/西式/火鍋/燒烤/早午餐/咖啡甜點/飲料冰品/酒吧餐酒館）+ 自由細類（拉麵、牛肉麵、法式甜點）。落類規則：菜系國別優先於品類（日式燒肉→日式），但店型優先於菜系（法式甜點→咖啡甜點）。台灣的縣市/行政區以 Google 地址文字為單一真相（Google 的行政區欄位時有時無，竹北市/竹東鎮從沒給過）；判不出的大類**留空不硬猜**，PWA 顯示成「其他」。`/美食推薦 中壢`、`/美食推薦 竹北` 直接命中行政區；打「新竹市」不會撈到新竹縣
- **地圖**（Phase 2）：`/美食地圖` → 產生 30 分鐘有效連結 → Google Maps 網頁，**藍 pin=想去、綠 pin=去過**；點 pin 看詳情（類型/推薦/評分/心得/🔥雷點/地址/Google Maps 連結）；上方「全部/想去/去過」可切換。地圖表面只有色點，雷點只在點開才顯示
- **貼連結自動記**（Phase 3）：在 `#美食輸入` 貼 IG/YouTube/TikTok/Threads/Facebook/Google Maps/一般網站連結 → bot 用 yt-dlp（主）+ og fetch 爬蟲 UA（備援）抽出 caption/描述 → 自動入庫並貼卡片；一則訊息含多個連結 → 平行處理一次多家入庫；抽不到店名（常見於 Threads/FB：店名在圖不在文字）→ 走 ⚠️ 補件卡（reply 補店名最快）。為防 SSRF，只會抓公網連結，內網/localhost/`file://` 等會被擋下
- **批次匯入**（Batch Import）：在 `#🍜-美食` 貼多行（markdown 待辦清單，`- [ ]`/`- [x]`）→ 一次批次匯入，回 ✅高信心/⚠️需確認/❌找不到 總結卡；`- [x]` 標去過。上限 60 行。
- **頻道分流**：`#美食輸入` 走美食流程、`#記帳` 走圖片記帳；其他頻道誤丟圖片會回一句指引（同頻道 30 分鐘內只回一次）。未設 `DISCORD_RECORD_CHANNEL_ID` 時圖片記帳退回「任意頻道」舊行為
- **店家照片庫**：照片檔存 `media/food/<店家id>/`、DB（`food_photos`）只記相對路徑與來源（app/bot/google）；`/api/food/places` 每家帶 `photos` 陣列。**自動補強**（enrich）：用 Google 評論萃取推薦菜 + 抓一張 Google 照片，idempotent 可重跑（目前由 `food.enrich.backfill_all()` 手動觸發）
- **手機版 PWA（開發中）**：前端 React app 放 `frontend/`，build 後由 FastAPI 掛在 `/m/`（沒 build 過會自動跳過掛載）。已可「加到主畫面」安裝（manifest + service worker）：離線開啟有 app 殼與上次載入的清單、店家照片快取 30 天。**持久登入**：第一次從 Discord 連結開啟時自動換發長效裝置 token（存手機本機），之後直接點主畫面 icon 就能用，不用回 Discord 重拿連結。**寫操作**：詳情面板可直接標「去過」（星等 1-5 + 一句心得）、拍照/相簿上傳店家照片（單張 5MB、每店 10 張）、刪照片；照片有來源標示（📸 自己拍 / 🤖 bot 收的 / 🔍 Google 的）。**消費分頁**：月導覽 + 收支三格頭 + 分類占比長條 + 按日流水帳；右下 ＋ 新增、點任一筆編輯/刪除（分類留空交給每週 AI 分類）。**食譜分頁**：🎰「今天煮什麼」拉霸隨機抽 + 清單（點一道可開連結/改名/刪除；新增食譜仍從 Discord 丟連結）。改完前端記得 `cd frontend && npm run build` 重新產出 dist/

### 食譜收錄
食譜收錄 — 把食譜連結丟進 `#🍳-食譜` 頻道，自動抽出乾淨菜名存庫；`/隨機食譜` 解決「今天煮什麼」。同 URL 去重、reply 卡片可改菜名、丟 Google Maps 連結會被擋。

### 歷史教學影片 🎥
歷史教學影片圖書館 — 把影片連結（YouTube 為主）丟進 `#📜-歷史教學` 頻道：yt-dlp 抓標題、AI 一次判**主題**（單一書架，如「世界史」）＋**標籤**（多個跨切，如「農業／戰爭／制度」）入庫。**三層編輯共用同一個 repo**：① AI 首判 ② Discord 回覆卡片增量微調（`#主題` 設書架、`+標籤`/`-標籤` 加刪、直接打字改標題；每張卡片底部固定附「越笨越好」回覆小抄，打 `help`/`?` 也回小抄）③ PWA 🎥 分頁主力編輯。資料用「主分類 + 去正規化多對多標籤」（`history_videos` + `video_tags`）。同 URL 去重，YouTube 縮圖免費當圖文清單。**PWA 🎥 分頁**：頂部主題書架 chips + 標題/標籤搜尋框，清單卡片帶縮圖，點卡片 → sheet 改主題/加刪標籤/開連結/刪除。

### AI 功能
- **Gemini 圖片辨識** — 拍照自動解析消費明細
- **AI 自動分類** — 每週日 21:00 自動將未分類帳目分類（也可手動觸發 `分類`），走 codex CLI（ChatGPT 訂閱制）。15 細類分 7 大組：
  - **固定**：居住水電 / 分期保險
  - **交通**：交通
  - **飲食**：三餐 / 聚餐 / 飲料零食 / 食材 / 超商
  - **生活**：日用品 / 家電3C / 醫療 / 服飾
  - **娛樂**：娛樂
  - **投資**：投資
  - **其他**：其他
- **AI 角色回應** — 記帳後由 persona 角色給出有趣評論（走 Gemini，求即時）。角色設定放 `persona.md`（本機私人檔，不入版控）；repo 附範本 `persona.example.md`（原創角色「錢鼠阿財」），沒有 `persona.md` 時自動退回範本。**看得到水位再說話**：每次記帳會附上本月四桶（投資/固定/生活/爽）用量、未分類金額與月份進度，角色依「桶位百分比 vs 月份進度」判斷該捧場還是該唸（**固定桶排除在外**——房租車貸月初一次付清，1 號就 100%，拿去比月份進度只會得出「你花太快」的荒謬結論，而且不可壓縮的支出唸了也沒用），**不以單筆金額大小論斷**（花三萬買 ETF 是好事，第五杯手搖才該被挑眉）。算不出水位時完全不傳，角色走保守模式、不做超支告誡
- **AI 週/月評語** — 週報/月報的理財評語走 codex CLI（ChatGPT 訂閱制，預設 `gpt-5.5`），免 Gemini 計費 API 的 429 配額困擾

> **文字 vs 影像分工**：帳目分類、週/月報評語等「純文字」生成走 codex 訂閱制；拍照記帳辨識、發票 CAPTCHA 破解等「影像」仍由 Gemini Vision 處理。codex 裝在 app 容器映像內（**非獨立服務**），登入憑證由 compose 掛載主機 `~/.codex` 到容器 `/root/.codex`。

### 電子發票自動同步
- **智能補拓（打卡高水位）** — 內部記錄「已成功涵蓋到哪一天」（`invoice_sync_state`）；每次同步自動算缺口並補抓：本月漏天加大查詢天數、跨月缺口逐月補（政府站限制同月查詢）。機器/網站關過幾天，恢復時自動把漏掉的天補回來，不再只抓前兩天。上限 60 天（更舊平台多半也查不到）。**全部載具全部月成功才推進高水位**；失敗則**在 `#🧾-發票通知` 發失敗卡 + 高水位不推進 + 下次自動重抓整段**（同張發票靠 `invoice_no` 去重，重抓安全）。
- **週一 ~ 週六 21:00 自動補拓** 並把當次新增明細以 embed 推到 Discord `#🧾-發票通知`
- **週日 21:00** 順序執行「補拓 → AI 分類 → 週報卡片」一條龍 pipeline，週報推到 `#📊-報表查詢`
- **開機後 3 分鐘** 背景補拓一次（機器關了又開盡快追上；只在有新發票或失敗才發卡）
- **手動觸發** — `抓發票`（抓今天）、`抓發票 7`（近 7 天）；手動指令不碰打卡高水位（純逃生口）
- **CAPTCHA 自動破解** — 用 Gemini Vision 辨識財政部圖形驗證碼
- **逐品項明細** — 點進每張發票 modal 抓出每一筆品名/金額各寫一筆支出（如超商的零食與生活用品分開記，分類才有意義）；抓不到明細才退化成「賣方＋總額」一筆
- **去重機制** — 以發票號碼為 key，重跑不會重複寫入
- **品項代號處理** — 純數字代號（如藥局商品 SKU）會自動加上賣方名前綴方便辨識

## 技術架構

| 層級 | 技術 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 資料庫 | PostgreSQL 15 (SQLAlchemy ORM) |
| AI（文字） | OpenAI Codex CLI（ChatGPT 訂閱制，分類 + 週/月報評語） |
| AI（影像） | Google Gemini API（拍照辨識 + CAPTCHA）|
| 訊息平台 | LINE Bot SDK 2.4.3 / discord.py |
| 排程 | APScheduler (背景排程) |
| 爬蟲 | Playwright + Chromium (財政部電子發票) |
| 前端報表 | ECharts 5 (純 HTML/JS) |
| 部署 | Docker Compose (app + PostgreSQL + ngrok) |

**Discord Bot 韌性**：Discord 是長連線 websocket（自己外連 gateway），啟動走監管迴圈 `run_discord_bot`——暫時性失敗（開機 DNS 未 ready、連線閃斷、gateway 重連耗盡）以指數退避（5s→cap 5 分）自動重試，直到接上；只有 `LoginFailure`（token 無效）才停手。取代舊版無監管的一次性 task（一拋例外就永久離線）。健康訊號 `🐉 Discord Bot 已上線` 與重試訊息都 `flush=True`，`docker logs` 即時可見。

## 環境變數 (.env)

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret（選填；與 ACCESS_TOKEN 缺任一則 LINE webhook 停用，不影響 Discord / PWA）|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token（選填，同上）|
| `DATABASE_URL` | PostgreSQL 連線字串 |
| `GEMINI_API_KEY` | Google Gemini API Key |
| `MODEL_NAME` | Gemini 模型名稱（影像辨識：拍照記帳 / CAPTCHA / 錢鼠阿財即時評論） |
| `CODEX_MODEL` | codex 模型覆蓋（選填，留空＝用 codex 預設 `gpt-5.5`；分類與週/月報評語用） |
| `MONTHLY_BUDGET` | 月度預算金額（選填，0 = 不顯示預算進度）|
| `MONTHLY_INCOME` | 三桶水位的收入基準（選填但**建議設**）。優先序：本月實收 → 上月實收 → 此值；都沒有則角色拿不到水位，走保守模式 |
| `BUCKET_RATIOS` | 四桶比例 `投資:固定:生活:爽`（選填，預設等分；建議 `2:4:2:2`）|
| `DISCORD_BOT_TOKEN` | Discord Bot Token（選填，未設定則跳過） |
| `DISCORD_INVOICE_CHANNEL_ID` | 發票通知頻道 ID（選填） |
| `DISCORD_REPORT_CHANNEL_ID` | 週報 / 月結通知頻道 ID（選填） |
| `DISCORD_RECORD_CHANNEL_ID` | 記帳主頻道 ID（選填，預留） |
| `BASE_URL` | 對外網址（報表/地圖連結用）；未設則用 ngrok 保留域名預設值 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | （選填）覆蓋 db 容器帳密；未設沿用預設。注意 postgres 只在 volume 首次初始化時套用密碼 |
| `FOOD_INGEST_CHANNEL_ID` | 美食輸入頻道 ID（美食地圖；丟截圖/文字自動記店） |
| `RECIPE_INGEST_CHANNEL_ID` | `#🍳-食譜` 頻道 ID；未設則食譜分支不啟用（不影響美食/記帳） |
| `HISTORY_VIDEO_INGEST_CHANNEL_ID` | `#📜-歷史教學` 頻道 ID；未設則影片分支不啟用（不影響其他模組） |
| `GOOGLE_PLACES_SERVER_KEY` | 後端 Google Places API (New) 金鑰（美食店名正規化 / 雷點摘要） |
| `GOOGLE_MAPS_BROWSER_KEY` | 前端 Google Maps JavaScript API 金鑰（美食地圖網頁；限 ngrok referrer + 只開 Maps JS API） |
| `GOOGLE_MAPS_MAP_ID` | Google Maps Map ID（AdvancedMarker 必需；未申請填 `DEMO_MAP_ID`，會有浮水印） |
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

# 4. 跑單元測試
docker compose exec app pytest tests/ -v
```

## CI

`.github/workflows/ci.yml`（GitHub Actions，push / PR 觸發）：

| Job | 做什麼 |
|-----|--------|
| `backend` | `pytest tests/`（427 個）+ **import 預檢**（`python -c "import main"`）|
| `frontend` | `npm ci` + `npm run build` |

兩個細節是踩過才知道的：

- **CI 必須給 `DATABASE_URL` 和假的 LINE 憑證**。`database.py` 在 import 時就 `create_engine()`、
  `line_handler.py` 在 import 時就 `LineBotApi(token)`，缺值不是「功能停用」而是**import 期直接崩潰**。
- **要裝 Chromium**。`tests/test_einvoice_{detail,pagination}.py` 會 `p.chromium.launch()` 開真瀏覽器；
  `importorskip` 只檢查套件有沒有裝，套件在 `requirements.txt` 裡，所以不裝瀏覽器是 **fail 不是 skip**。

`import main` 這關是刻意設的：這個 repo 最痛的一次生產中斷就是「加端點忘了裝 `python-multipart`
→ import 期 RuntimeError → bot + webhook 全掛」。**import 崩潰＝全站掛**，所以把它擋在 CI。

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
所有回覆用彩色 embed 卡片（💸 支出紅、💰 收入綠、🔍 查詢藍、🐭 錢鼠阿財紫）。

**頻道結構**（一次性 setup 腳本建立，含主題 banner 圖（圖檔在 gitignore 的 resource/，不入版控））：
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
| `/測試週報` / `/測試月報` | 手動觸發推送本週週報 / 上月月報到 #📊-報表查詢（ephemeral 回覆） |
| `/說明` | 顯示所有指令 |
| 拖曳圖片 | AI 辨識發票/明細 |
| `/美食新增 店名 [區域] [推薦品項]` | 美食地圖 Phase 1A — 查 Google 正規化後加入想去清單 |
| `/美食推薦 地區` | 依縣市/鄉鎮市區/國家列出想去清單，含 🎲 隨機挑一家（例：中壢 / 新竹市 / 日本） |
| `/美食清單 [狀態]` | 列出美食清單（想去 / 去過 / 全部） |
| `/去過 編號 [評分] [心得]` | 將店家標為去過，可記 1-5 星評分與心得 |
| `/美食地圖` | 產生 Google Maps 網頁連結（藍=想去/綠=去過，點 pin 看詳情，可切換） |
| `/美食刪除 編號` | 依編號刪除一家店（修正批次猜錯的分店） |
| `/隨機食譜` | 從收錄的食譜裡隨機抽一道 |
| `/食譜清單` | 列出所有收錄的食譜 |
| `/食譜刪除 編號` | 刪除一筆食譜 |
