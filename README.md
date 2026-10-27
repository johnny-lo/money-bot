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
- **互動式網頁報表** — `報表`（產生 30 分鐘有效的一次性連結），或從手機 PWA 消費分頁右上角的 **📊 報表** 直接開
  - 每日/每月收支趨勢折線圖
  - 支出分類圓餅圖
  - 近 6 個月柱狀圖對比
  - 流水帳明細（含新增/編輯/刪除功能）
  - **點圖表就篩明細**：點圓餅的分類、點折線的某一天、點長條的某個月 → 下面的流水帳只留符合的，
    並出現「篩選中：飲食 ✕ · 09/15 ✕ · 12 筆 · 支出 $3,200 ｜清除」摘要列。
    條件**疊加取交集**（所以問得出「這個月飲食花最多的是哪一天」），點同一個第二次取消。
    折線與長條**點整欄都算**，不必戳中那顆小圓點。單月模式下點長條圖＝跳到那個月。
    上方三格頭維持整月總額不動，篩選後的數字只出現在摘要列。

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
- **手機版 PWA（開發中）**：前端 React app 放 `frontend/`，build 後由 FastAPI 掛在 `/m/`（沒 build 過會自動跳過掛載）。已可「加到主畫面」安裝（manifest + service worker）：離線開啟有 app 殼與上次載入的清單、店家照片快取 30 天。**持久登入**：第一次從 Discord 連結開啟時自動換發長效裝置 token（存手機本機），之後直接點主畫面 icon 就能用，不用回 Discord 重拿連結。**寫操作**：詳情面板可直接標「去過」（星等 1-5 + 一句心得）、拍照/相簿上傳店家照片（單張 5MB、每店 10 張）、刪照片；照片有來源標示（📸 自己拍 / 🤖 bot 收的 / 🔍 Google 的）。**消費分頁**：月導覽 + 收支三格頭 + 分類占比長條 + 按日流水帳；右下 ＋ 新增、點任一筆編輯/刪除（分類留空交給每週 AI 分類）。**點分類長條或日期標頭＝篩選**（疊加取交集、再點一次取消、摘要列可單獨叉掉條件），語意與網頁報表共用同一份純函式 `ledgerFilter.js`。右上角 **📊 報表** 開完整圖表報表（前端先用裝置 token 換一顆 30 分鐘短效 token 再開新分頁——網頁導航送不出 header，而長效 token 不該進網址列）。**食譜分頁**：🎰「今天煮什麼」拉霸隨機抽 + 清單（點一道可開連結/改名/刪除；新增食譜仍從 Discord 丟連結）。**信件分頁 📬**（唯讀）：總覽是一格一層的小卡（名稱＋筆數；🛡 保護名單一組、其餘類別一組，全部 0 筆顯示「還沒同步過信件」），點進去看該層名單，有返回鈕、搜尋框（停止輸入 300ms 才重抓）、「載入更多」每次再接 200 筆；資料來自 `/api/mail/overview`、`/api/mail/layers/{key}`；信件 API 刻意不進離線快取（寄件者與主旨是私人資料，也免得擠掉其他分頁的離線清單），離線時只顯示連線錯誤。改完前端記得 `cd frontend && npm run build` 重新產出 dist/

### 食譜收錄
食譜收錄 — 把食譜連結丟進 `#🍳-食譜` 頻道，自動抽出乾淨菜名存庫；`/隨機食譜` 解決「今天煮什麼」。同 URL 去重、reply 卡片可改菜名、丟 Google Maps 連結會被擋。

### 歷史教學影片與文章 🎥📄
歷史教學圖書館 — 把影片連結（YouTube 為主）或文章網頁連結丟進 `#📜-歷史教學` 頻道：影片（YouTube／IG／TikTok／FB）用 yt-dlp 抓標題；文章用一般瀏覽器 UA 抓網頁，取標題（og:title，沒有就 `<title>`）、描述與內文重點（`<article>`→`<main>`→所有 `<p>`，去掉 script／style／nav／header／footer，前 3,000 字）；標題缺、或描述與內文都缺時，換 `facebookexternalhit` 爬蟲 UA 再抓一次（Threads 只對爬蟲 UA 給 og 標題與描述，所以先用爬蟲 UA）；網頁編碼先看 HTTP header，沒宣告就看開頭 2KB 的 `<meta charset>`／http-equiv（Big5 舊站標題不亂碼），都沒有當 UTF-8；抓不到內文仍用標題＋描述分類，完全抓不到標題才回「沒收進來」。AI 一次判**主題**（單一書架，如「世界史」）＋**標籤**（多個跨切，如「農業／戰爭／制度」）入庫。**三層編輯共用同一個 repo**：① AI 首判 ② Discord 回覆卡片增量微調（`#主題` 設書架、`+標籤`/`-標籤` 加刪、直接打字改標題；每張卡片底部固定附「越笨越好」回覆小抄，打 `help`/`?` 也回小抄）③ PWA 🎥 分頁主力編輯。資料用「主分類 + 去正規化多對多標籤」（`history_videos` + `video_tags`）。同 URL 去重，YouTube 縮圖免費當圖文清單。影片還是文章由 `platform` 推（youtube／instagram／tiktok／facebook＝影片，其餘＝文章），API 回 `kind`（`video`／`article`）；Discord 卡片標題與 PWA 清單都標出 🎥 影片或 📄 文章，沒有縮圖的文章顯示 📄 佔位。**PWA 歷史分頁**：頂部主題書架 chips + 標題/標籤搜尋框，清單卡片帶縮圖，點卡片 → sheet 改主題/加刪標籤/開連結/刪除。

### AI 功能
- **外部服務故障會講人話** — Google Places 掛掉時（金鑰被擋、專案帳單失效、配額用完），
  卡片會說「服務暫時不可用，不是這家店的問題」而不是「找不到，加上地區再重貼」；
  伺服器 log 同時留下原因與**連續失敗次數**（`⚠️ Places 查店家 失敗（連續第 N 次）：…`）
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
- **AI 週/月評語** — 週報/月報的理財評語走 codex CLI（ChatGPT 訂閱制，模型用 `~/.codex/config.toml` 的設定），免 Gemini 計費 API 的 429 配額困擾

> **文字 vs 影像分工**：帳目分類、週/月報評語等「純文字」生成走 codex 訂閱制；拍照記帳辨識、發票 CAPTCHA 破解等「影像」仍由 Gemini Vision 處理。
> **影像有退避鏈**（`gemini.vision_text()`）：`MODEL_NAME` → `GEMINI_FALLBACK_MODELS` 逐個試 → 最後退 codex。單一模型是單點故障——`gemini-flash-latest` 這種 alias 一忙就整串 503，2026/08/24~08/29 就這樣讓發票同步連續多天空轉。**CAPTCHA 例外，不退 codex**（codex 政策上拒絕辨識驗證碼），只在 Gemini 各模型間退避。codex 裝在 app 容器映像內（**非獨立服務**），登入憑證由 compose 掛載主機 `~/.codex` 到容器 `/root/.codex`。
> **結構化輸出**：要抽欄位的呼叫（拍照記帳、分類、美食／食譜／影片抽取、推薦菜）都帶 JSON Schema——Gemini 走 `responseJsonSchema`、codex 走 `--output-schema`，退避鏈上不論哪一層接手，回來的都是同一個形狀的 JSON。

### 電子發票自動同步
- **智能補拓（打卡高水位）** — 內部記錄「已成功涵蓋到哪一天」（`invoice_sync_state`）；每次同步自動算缺口並補抓：本月漏天加大查詢天數、跨月缺口逐月補（政府站限制同月查詢）。機器/網站關過幾天，恢復時自動把漏掉的天補回來，不再只抓前兩天。上限 60 天（更舊平台多半也查不到）。**全部載具全部月成功才推進高水位**；失敗則**在 `#🧾-發票通知` 發失敗卡 + 高水位不推進 + 下次自動重抓整段**（同張發票靠 `invoice_no` 去重，重抓安全）。**登入失敗也算失敗**——不會被當成「這幾天沒有發票」默默跳過。
- **週一 ~ 週六 21:00 自動補拓** 並把當次新增明細以 embed 推到 Discord `#🧾-發票通知`
- **週日 21:00** 順序執行「補拓 → 刷卡比對 → AI 分類 → 週報卡片」一條龍 pipeline，週報推到 `#📊-報表查詢`
- **開機後 3 分鐘** 背景補拓一次（機器關了又開盡快追上；只在有新發票或失敗才發卡）
- **手動觸發** — `抓發票`（抓今天）、`抓發票 7`（近 7 天）；手動指令不碰打卡高水位（純逃生口）
- **CAPTCHA 自動破解** — **本地 ddddocr 優先**（實測 30 張真圖 30/30、4.4 ms/張、不出網），解不出來才退到 Gemini Vision 的模型退避鏈。順手把登入成功的 (圖, 答案) 存成樣本（上限 1GB，超過刪最舊），哪天財政部改字型可以直接拿來重訓
- **逐品項明細** — 點進每張發票 modal 抓出每一筆品名/金額各寫一筆支出（如超商的零食與生活用品分開記，分類才有意義）；抓不到明細才退化成「賣方＋總額」一筆
- **去重機制** — 以發票號碼為 key，重跑不會重複寫入
- **品項代號處理** — 純數字代號（如藥局商品 SKU）會自動加上賣方名前綴方便辨識
- **記下賣方是誰**（`transactions.seller`）— 每筆發票消費都存下**賣方原始全名**（「全家便利商店股份有限公司」，
  而非精簡後的「全家便利商店」）。精簡是純函式、要顯示時隨時能套；反過來原始值沒存就永遠救不回來。
  這是「這家店我們去過幾次、總共花多少」（`transactions` × `food_places`）的資料基礎。
  ⚠️ **歷史資料補不回來**：舊版抓到賣方卻沒寫進 DB，賣方在爬蟲當下就丟了 →
  既有 697 筆發票消費的 seller 永遠是空的，**這個欄位從上線那天起才開始累積**。

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
| 部署 | Docker Compose (app + PostgreSQL + line) + Tailscale Funnel 對外 |

**Discord Bot 韌性**：Discord 是長連線 websocket（自己外連 gateway），啟動走監管迴圈 `run_discord_bot`——暫時性失敗（開機 DNS 未 ready、連線閃斷、gateway 重連耗盡）以指數退避（5s→cap 5 分）自動重試，直到接上；只有 `LoginFailure`（token 無效）才停手。取代舊版無監管的一次性 task（一拋例外就永久離線）。健康訊號 `🐉 Discord Bot 已上線` 與重試訊息都 `flush=True`，`docker logs` 即時可見。

### 刷卡比對（找出載具沒記到的消費）
- **資料來源**：從 Gmail（唯讀）抓**永豐每日消費通知**、**中信月帳單**的加密 PDF，用身分證字號（大寫）解開、逐筆解析。
  永豐每日通知沒有店名；中信的中文店名在 PDF 裡是圖片，由 **Codex 讀圖**補上（每 25 行一批，行數對不上就放棄、下次再試）。
  Autopass 停車收據與永豐「網路消費通知」（內文有商店名稱）只用來替同金額的刷卡補店名；永豐網路消費通知有寫卡號末四碼，
  卡號不同就不配（避免同金額、日期相近的別張卡被套上店名）。永豐實體店消費信箱裡沒有店名，維持空白。
  DAWHO「信用卡交易」是**繳卡費**，刻意不抓（抓了會重複算）。
- **比對**：每筆刷卡找「同金額、帳上日期在刷卡日 −1～+3 天」的帳目，一對一配對；發票先把同張發票的品項加總成整張金額再比。
  **永豐刷卡有時間（HH:MM）**，發票也存了開立時間（見下），所以先找「同金額、時間差 10 分鐘內」的發票；
  沒有單張同金額時，10 分鐘內 2～4 張發票加起來剛好等於刷卡金額也算配到（一筆刷卡、多張發票）。找不到才走日期差。
  中信帳單沒有時間，照日期比；手記帳的時間是記帳時間，不參與時間比對。每週重比一次（發票可能晚幾天才同步進來）。
- **週日清單卡**：沒配到、刷卡滿 3 天、2026-04-21（開始用載具記帳那天）以後的刷卡——目的是找出「有刷卡、沒有載具發票」的消費，每 25 筆一張卡推到 `#🧾-發票通知`。
  下拉勾選要忽略的（例如其實是另一半記的），再按「📝 全部補記」→ 寫進 `transactions`（`source=信用卡`，
  品名＝店名或「信用卡消費（US）」，分類交給下次週日 AI 分類）。**只有本人能按**；補記前會再比一次，這週剛進來的發票不會被重複記；按兩次第二次是 0 筆；bot 重啟後按鈕照樣能按。
- **分組＋判斷線索**：清單依序分成「疑似訂閱或固定扣款／海外消費／小額（≤100 元）／其他」，每組各自分頁。
  每行只寫銀行（「中信」「永豐」，不標卡號）、附刷卡時間（永豐才有），以及線索「同卡同金額 N 個月都有」（3 個月以上才標）。
  刷卡金額與發票金額不會有差，金額不同就是不同消費，所以帳上金額相近或時間相近的紀錄不當線索。整張看完都不用補，按「🙈 全部忽略」。
- **店名換品牌**：店名或公司名（例如「某某股份有限公司某某分公司」「某某餐廳－123」）由 Codex 換成一般人認得的品牌，
  快取在 `merchant_brands`、每個原名只問一次；清單每行與補記進帳目的品名都顯示品牌，原名留在 `card_charges.merchant`。
  分期保留期數：「富邦EC分期03-03」顯示成「富邦EC（分期 3/3）」。
- **已列過的不會重列**；舊卡的按鈕一直有效。解密失敗或解析 0 筆的信會另發警告卡（銀行改版或密碼變了的訊號）。

### 中信 LINE 刷卡通知（`money-line` 容器）
- **做什麼**：讀本人個人 LINE 裡官方帳號「中國信託」推的消費通知，刷卡後約 1 分鐘內寫進刷卡比對（來源 `ctbc_line`），
  帶刷卡時間（到分鐘）與實體店店名；網路消費沒有店名，清單上顯示商店類型。不用等月帳單，週日清單就有完整的中信刷卡。
- **怎麼讀**：非官方的 [OkLine](https://github.com/NiceDayZc/OkLine)（模仿 LINE Chrome 擴充功能的協定），固定在審過的 commit，
  build 時驗 LINE 程式檔的 sha256。**只讀**：不傳訊息、不送已讀、不改設定；其他聊天室的訊息在記憶體裡就丟掉，不存、不 log。
  自動化個人帳號違反 LINE 條款，帳號有被限制的風險；LINE 公告要停掉 Chrome 版，停了這條就斷，退回只靠月帳單。
- **獨立容器**：LINE 登入檔（等於整個帳號加解密金鑰）只在 `money-line`，主機路徑 `~/.config/money-bot/line/tokens.json`；
  容器只拿得到 DB 連線，碰不到 codex、Discord token 與其他機密。同一個 LINE 帳號只能有一個 Chrome 版登入：
  **Chrome 裡不要再登入 LINE**，一登入就會把 listener 擠掉（LINE 電腦版是另一個位置，不受影響）。
- **跟月帳單合成一筆**：之後中信月帳單的同一筆（同卡號末四碼、同金額、同日，找不到才放寬一天）會合成一筆，
  不會在清單出現兩次；LINE 的店名與時間優先，帳單補上入帳日。海外商店的通知（有「外幣金額」）只是台幣約當金額，
  不建刷卡、等帳單。分期或請款金額跟授權金額不同的刷卡不合併，兩邊各算一筆。
- **拆不出來時**：通知版型認不得就交給 Codex（sol 模型）抽欄位、嚴格驗證；還是不行就在 `#🧾-發票通知` 發卡給本人看。
  週日刷卡比對另附一行「📡 LINE 中信通知：本週 N 筆 · 合併帳單 M 筆 · 狀態」。
- **被登出時**：Discord 會通知。在 repo 目錄跑下面這行、用手機 LINE 掃 QR 並確認 PIN；listener 會自己發現新的登入接著收，不用重啟：
  ```bash
  docker compose run --rm line okline login --save /data/tokens.json --wait 240
  ```

### 信件整理（Gmail 歷史整理＋每日整理）
- **信箱**：`.env` 的 `GMAIL_ADDRESS` 那個 Gmail（定位是正式對外聯絡＋求職）。**只讀信頭、不讀內文**；寫入只有三種：
  建標籤、加／拿掉標籤（含移出收件匣）、丟垃圾桶（30 天內救得回，**從不永久刪除**）。
  寫入一個指令一次處理最多 50 封（同種類、同標籤的信一組，順序是加標籤 → 移出 → 丟垃圾桶），整組失敗才退回逐封，大量整理幾分鐘跑完。
- **分類**：寄件者＋主旨樣式（去掉 Re/Fwd、數字遮成 #、本人姓名遮掉）→ 14 類（安全警示、寄給自己、稅務保單、學校、
  刷卡扣款、收據訂單、帳單、國內旅遊／交通、出國旅遊、公司系統通知、職缺推薦、LinkedIn 社群、登入驗證碼、推銷電子報），各類有保留期限
  （例如推銷 14 天後丟、刷卡扣款與收據滾動 2 年、國內旅遊 180 天後丟；**帳單／對帳單與出國旅遊不刪**，只加標籤、移出收件匣；學校只加標籤移出）。另有兩個 AI 建議和 Discord 手動指定都不給的類別：
  「重要」（留收件匣、不加標籤；只由安全網判定）與 **「求職」（留收件匣、只加 `整理/求職` 標籤，不移出、不丟）**。
  求職除了安全網判定，規則也可以是求職（由本人在 Claude Code 指定）；規則判成求職的信同樣只加標籤、不移出、不丟。
  - **求職的範圍**：已確認重視公司寄來、沒有退訂連結的信，加上任何寄件者寄來、主旨有**強**求職字眼（面試、面談、錄取、
    錄用、複試、二面、到職、聘書、聘任、interview、job offer、offer letter、application status）、沒有退訂連結的信
    （人力銀行面試邀請、獵頭、學校就業處）。只有弱字眼（邀請、報到、測驗…）而且不是重視公司寄的信、有退訂連結的信、
    真人來信，照樣留收件匣但不加標籤。
- **安全網（命中就留收件匣、不自動處理）**：
  1. 主旨有求職字眼（面試、邀請、錄取、offer…）的那一封，任何規則都蓋不掉（歸「求職」或「重要」，見上）；
  2. **重視的公司**：寄過「面試、面談、錄取、interview、offer letter…」這類**強**字眼的公司網域，先發「🛡 新的重視公司」確認卡，
     **本人確認才生效**；群發信（有退訂連結）與學校網域不學、也不保護；
  3. **像真人寄的**：免費信箱（gmail、yahoo…）或「名.姓」形式、且沒有退訂連結的地址；no_reply、系統代號、品牌帳號不算。
- **確認卡**：新的「寄件者＋樣式」由內建規則或 AI（codex）預填類別，**每類一張整批核可卡**：列封數最多的 25 個寄件者，
  每個寄件者除了地址，還附顯示名稱和卡上樣式最近一封信的主旨，看得出是哪家公司寄了什麼（名稱與主旨只當純文字顯示，寄件者寫的連結語法或 @ 提及不會變成連結、也不會 tag 人）；
  下拉勾掉不是這類的（選項標名稱、說明是「地址｜主旨」），按「✅ 整類確認」其餘一起生效；被勾掉的寄件者再用下拉手動指定類別。完整名單看 `/信件名單 層:你的規則`
  或手機 PWA 📬（搜尋框打類別名稱就能篩）。只有本人能按。
- **歷史整理**：卡都處理完會發「🗂 歷史信件整理計畫」卡（各類要加標籤／移出／丟幾封＋範例主旨），本人按「🚀 執行歷史整理」才動信；
  計畫卡發出後又確認了規則或重視公司，舊的執行鈕會回「計畫已過期」。
- **推銷寄件者的「任何主旨」規則**：同一個完整寄件地址的已確認規則全部是推銷（沒有其他類別、沒有被拒絕或待確認的規則）、
  寄件網域不在已確認重視公司，每日整理在抓完新信頭之後、分類之前自動補一條「這個地址任何主旨＝推銷」規則，電子報每期換主旨也不會再開新卡；
  之後這個地址又有了別的類別、被拒絕或待確認的規則（例如手動指定改選別的類別），下次每日整理會把自動補的那條移除。
  混寄（同地址也寄收據、通知）的地址維持逐主旨，也不補 `@網域` 的規則。安全網第 1 條照樣蓋過任何規則。
- **每日整理（23:30）**：抓新信頭→補（或移除）推銷寄件者的任何主旨規則→分類→到期的動作照做（歷史整理完成前只分類不動信）→每日報告卡（含安全網留下的信）、
  每日職缺摘要、週日推銷摘要；新的寄件者樣式照樣發整批核可卡。頻道：`MAIL_CHANNEL_ID`。

## 環境變數 (.env) 與機密 (secrets)

設定分兩類：**一般設定**放 `.env`（下表）；**12 個機密**（`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`DISCORD_BOT_TOKEN`、`GEMINI_API_KEY`、`GOOGLE_PLACES_SERVER_KEY`、`DATABASE_URL`、`EINVOICE_PHONE_1/2`、`EINVOICE_PASSWORD_1/2`、`GMAIL_APP_PASSWORD`、`NATIONAL_ID`）放 repo 外的 `~/.config/money-bot/secrets/<小寫名>`（目錄 700、檔案 600），由 compose `secrets:` 掛進容器 `/run/secrets/`，程式經 `app_secrets.get_secret()` 讀，不會出現在容器環境變數。選填的機密沒值也要有空檔（搬遷腳本會建）。下表標 🔐 的就是機密。

| 變數 | 說明 |
|------|------|
| 🔐 `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret（選填；與 ACCESS_TOKEN 缺任一則 LINE webhook 停用，不影響 Discord / PWA）|
| 🔐 `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token（選填，同上）|
| 🔐 `DATABASE_URL` | PostgreSQL 連線字串 |
| 🔐 `GEMINI_API_KEY` | Google Gemini API Key |
| `MODEL_NAME` | Gemini 主模型（影像辨識：拍照記帳 / CAPTCHA / 錢鼠阿財即時評論） |
| `GEMINI_FALLBACK_MODELS` | 選填。影像辨識備援模型，逗號分隔，主模型失敗**或拒答**時依序往下試 |
| `CAPTCHA_SAMPLE_DIR` | 選填。驗證碼樣本目錄，預設 `data/captcha`（已 gitignore） |
| `CAPTCHA_SAMPLE_MAX_BYTES` | 選填。樣本目錄容量上限，預設 1GB，超過從最舊的開始刪 |
| `CODEX_MODEL` | codex 模型覆蓋（選填，留空＝用 `~/.codex/config.toml` 設定的模型；分類與週/月報評語用） |
| `MONTHLY_BUDGET` | 月度預算金額（選填，0 = 不顯示預算進度）|
| `MONTHLY_INCOME` | 四桶水位的收入基準（選填但**建議設**）。優先序：本月實收 → 上月實收 → 此值；都沒有則角色拿不到水位，走保守模式 |
| `BUCKET_RATIOS` | 四桶比例 `投資:固定:生活:爽`（選填，預設等分；建議 `2:4:2:2`）|
| `SHARED_SPLIT` | 共同分攤支出在「我的桶位」裡算幾成（選填，預設 `0.5`）。DB 存全額，只有算桶位時折 |
| 🔐 `DISCORD_BOT_TOKEN` | Discord Bot Token（選填，未設定則跳過） |
| `DISCORD_INVOICE_CHANNEL_ID` | 發票通知頻道 ID（選填） |
| `DISCORD_REPORT_CHANNEL_ID` | 週報 / 月結通知頻道 ID（選填） |
| `DISCORD_RECORD_CHANNEL_ID` | 記帳主頻道 ID（選填，預留） |
| `BASE_URL` | 對外網址（報表/地圖連結、LINE webhook 用）。必填 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | （選填）覆蓋 db 容器帳密；未設沿用預設。注意 postgres 只在 volume 首次初始化時套用密碼 |
| `FOOD_INGEST_CHANNEL_ID` | 美食輸入頻道 ID（美食地圖；丟截圖/文字自動記店） |
| `RECIPE_INGEST_CHANNEL_ID` | `#🍳-食譜` 頻道 ID；未設則食譜分支不啟用（不影響美食/記帳） |
| `HISTORY_VIDEO_INGEST_CHANNEL_ID` | `#📜-歷史教學` 頻道 ID；未設則影片／文章分支不啟用（不影響其他模組） |
| 🔐 `GOOGLE_PLACES_SERVER_KEY` | 後端 Google Places API (New) 金鑰（美食店名正規化 / 雷點摘要） |
| `GOOGLE_MAPS_BROWSER_KEY` | 前端 Google Maps JavaScript API 金鑰（美食地圖網頁；限 ngrok referrer + 只開 Maps JS API） |
| `GOOGLE_MAPS_MAP_ID` | Google Maps Map ID（AdvancedMarker 必需；未申請填 `DEMO_MAP_ID`，會有浮水印） |
| 🔐 `EINVOICE_PHONE_1` | 第一組載具：財政部電子發票會員手機號碼 |
| 🔐 `EINVOICE_PASSWORD_1` | 第一組載具：驗證碼（密碼） |
| 🔐 `EINVOICE_PHONE_2` | 第二組載具（選填） |
| 🔐 `EINVOICE_PASSWORD_2` | 第二組載具密碼（選填） |
| `GMAIL_ADDRESS` | 刷卡比對與信件整理用的 Gmail 帳號（不是機密；密碼走 🔐 `GMAIL_APP_PASSWORD`、PDF 密碼走 🔐 `NATIONAL_ID`）|
| `MAIL_CHANNEL_ID` | 信件整理的 Discord 頻道（確認卡、計畫卡、每日報告）；沒設就什麼都不發 |
| `MAIL_OWNER_NAME` | 本人姓名（主旨樣式遮掉它，也不送給 AI）；只放 `.env`，不進 repo |
| `MAIL_SELF_ADDRESSES` | 本人其他信箱（逗號分隔）：從這些地址寄來的歸「寄給自己」 |
| `MAIL_COMPANY_DOMAINS` | 目前公司的網域（逗號分隔）：不會被學成「重視的公司」，系統通知歸「公司系統通知」 |
| `HEALTHCHECK_DISCORD_WEBHOOK` | 對外健康檢查的告警 webhook（選填，沒設就只寫 log）。**主機上的 `scripts/healthcheck.sh` 讀，不是容器讀** → 刻意不寫進 `docker-compose.yml` |
| `HEALTHCHECK_FAIL_THRESHOLD` / `HEALTHCHECK_RESOLVER` / `HEALTHCHECK_FUNNEL_PORT` | 健康檢查微調（選填，預設 `2` / `1.1.1.1` / `8000`）|

## 快速啟動

```bash
# 1. 設定環境變數：先在 .env 填好（含機密），再把機密搬進 secrets 檔
cp .env.example .env
bash scripts/migrate_secrets.sh   # 機密 → ~/.config/money-bot/secrets/，.env 備份在其上一層 env.bak.*

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
| `backend` | `pytest tests/` + **import 預檢**（`python -c "import main"`）+ `scripts/healthcheck.sh --self-test`（31 項純邏輯，不出網）|
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
- LINE Webhook URL: `<BASE_URL>/callback`

### 對外出口：Tailscale Funnel

```bash
tailscale funnel --bg 8000          # 開，網址即 https://<機器>.<tailnet>.ts.net
tailscale funnel status             # 看目前設定
tailscale funnel --https=443 off    # 關
```

**為什麼不是 ngrok**：ngrok 免費版對瀏覽器請求回攔截頁，而**瀏覽器抓 service worker 時
帶不了自訂 header** → 拿到 `text/html` → SW 註冊靜默失敗 → 手機永遠卡舊版。這是無解的
（攔截頁在 ngrok 邊緣、那個請求也插不了 header），只能離開免費版。Tailscale Funnel 免費、
沒有攔截頁、網址固定，且訪客不需要安裝 Tailscale。詳見 `AGENTS.md`。

### 對外健康檢查（自動修復 Funnel）

主機重開機後踩過一次：**所有本地指標全綠**（`docker ps` Up、`curl localhost:8000` 200、
`tailscale funnel status` 顯示 `Funnel on`、`tailscale status` Online 無警告）
**但外部裝置完全連不上**——Funnel 的*設定*活過了重開機，*入口註冊*沒有。

更麻煩的是：在主機上 `curl https://<機器>.ts.net/...` 也回 200，因為 **MagicDNS 把它解析到
tailnet 內網 IP（100.x），根本沒走 Funnel**。所以「我 curl 過了」對這個故障零證據力。

`scripts/healthcheck.sh` 就是為了這個而生——它是唯一會從**公開路徑**問問題的東西：

```bash
IP=$(dig +short @1.1.1.1 <host> A | head -1)      # 公開解析器，不是系統解析
curl --resolve "<host>:443:$IP" https://<host>/healthz
```

| 行為 | 說明 |
|------|------|
| 檢查什麼 | `GET /healthz`（免 token，會順手驗 DB；見下方） |
| 從哪打 | 公開解析器查到的 Funnel 入口 IP，`curl --resolve` 強制走它。**IP 每次重查，不寫死** |
| 何時動作 | **連續 2 次**失敗（單次多半是網路抖動）|
| 怎麼修 | `tailscale funnel --https=443 off` → `tailscale funnel --bg 8000` → 等 6 秒 → 重驗 |
| 修好了 | Discord 通知「已自動修復」（**成功也說話**，不是只在壞掉時出聲）|
| 修不好 | 通知後**停手**，不再每 5 分鐘踢一次正在用的服務；人工處理完跑 `--reset` 解除 |
| 自己好了 | 通知「已恢復」並解除閂鎖 |
| **不會做的事** | **app 壞掉時不碰 Funnel**——TLS 握手成功就代表入口是好的，那時重掛只是把好的關掉再開；這種情況只通知並指向 `docker logs money-bot` |

**安裝**（user timer，不需要 sudo）：

```bash
# 1. 先讓容器有 /healthz（這個端點是新加的，舊容器沒有）
docker restart money-bot        # 等 log 出現 Application startup complete

# 2. 手動驗一次（應該印「✅ 健康」）
./scripts/healthcheck.sh
./scripts/healthcheck.sh --self-test    # 純邏輯自測，不出網、不碰 funnel

# 3. 選填：Discord 通知（沒設就只寫 log）
#    在 .env 加一行 HEALTHCHECK_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...

# 4. 裝 timer
mkdir -p ~/.config/systemd/user
cp scripts/systemd/linebot-healthcheck.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now linebot-healthcheck.timer

# 5. 確認
systemctl --user list-timers linebot-healthcheck.timer
journalctl --user -u linebot-healthcheck -n 30
```

- **順序很重要**：先 `docker restart` 再裝 timer。否則 `/healthz` 回 404，
  兩輪後就會收到一則「服務說自己不健康」的假警報（不過它**不會**去動 Funnel，因為 404
  被歸類成 app 問題）。
- unit 檔裡的 `ExecStart` 路徑寫死成 `~/Desktop/linebot`，repo 放別處要改。
- 機器沒登入也要跑 → 需要 `loginctl enable-linger $USER`（本機已是 `Linger=yes`）。
- 需要 `dig`（`dnsutils`）、`curl`、`jq`、`flock`。**不能拿 `getent`/`host` 代替 `dig`**，
  那會走 MagicDNS，等於又在驗內網。

其他指令：`--status`（看狀態檔）、`--reset`（解除「已停手」閂鎖）、`--help`。

### 🛠 自動修復（持續性 bug 自動喚醒 Claude Code）

同一個問題**持續發生**時，主機上的 Claude Code 會被自動叫醒：在隔離的 git worktree 裡照
`superpowers:systematic-debugging` 找根因、照 TDD 修好，把 debug 報告丟到 Discord `#🛠-自動修復`。
**不會自己上線**——你在手機上按 **✅ 部署** 才合併、測試、重啟、上線驗證；任何一步失敗自動 revert 回合併前。

| 感測器 | 觸發條件 |
|---|---|
| 發票登入失敗 | 同一載具 3 個不同日子都登入失敗 |
| 排程任務例外 | 同一個 job 以同一種例外連續失敗 3 次 |
| 連結抽取失敗 | 同一模組同一平台（IG、Threads…）7 天內 3 條不同網址抽取失敗 |

報告卡三種結論：**✅ 修好了**（附 diff、測試、重現結果，有部署/放棄鈕）／**🙋 需要你處理**（根因不在程式：密碼過期、帳號被鎖、外部服務掛了）／
**❓ 沒找到可靠的修正**（附已排除的假設）。每張卡附 `claude --resume <id>` 讓你接手細看。

**安全邊界**：部署鈕只有 `AUTOFIX_OWNER_USER_ID` 按得動、7 天內有效；Claude 只能在 worktree 內改後端 Python 與文件，
worktree 放在 `/var/tmp`、讀取權限封鎖整個家目錄（讀不到你的其他專案、`.env`、憑證），不能碰 docker、前端、`git push/merge`、上網；碰真實網站只能經 `autofix/bin/probe`，
**財政部登入每事件最多 3 次 probe、每次最多送出 1 次，由主機端計數**（帳號累計 40 次錯誤會被鎖；部署後的上線驗證另外會正常登入一次）；宣稱修好但測試沒全綠／沒 commit／改到禁區，一律降級不給部署鈕；
修好不到 7 天又壞 → 不再自動修，直接請你處理。部署不會 push。

**安裝**：
```bash
bash autofix/install.sh                       # 建交接目錄 + 安裝 systemd user units
# .env 加 AUTOFIX_ENABLED=1、AUTOFIX_CHANNEL_ID、AUTOFIX_OWNER_USER_ID
docker compose up -d                          # env 變更要 up -d，不是 restart
docker exec -w /app money-bot python -m autofix.drill   # 演習：故意弄壞一個函式，走完整流程
```
看進度：`journalctl --user -u linebot-autofix-run -f`、`journalctl --user -u linebot-autofix-deploy -f`。

### `/healthz`

```
GET /healthz  →  200 {"status":"ok"}          # app 活著且 DB 通
              →  503 {"status":"unavailable"} # DB 不通
```

**免 token**（檢查器要在服務壞掉時還問得到答案，讓它持有憑證只是多一個會外洩的東西），
所以回應被當成公開資訊：**不回版本號、路徑、環境變數、DB 連線字串，連例外訊息都不轉出去**
（SQLAlchemy 的錯誤字串裡就有帳密與主機名）——細節只進伺服器 log。回應帶 `Cache-Control: no-store`，
因為健康檢查拿到快取的舊答案就等於謊報健康。

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
| `固定 支出 房租 12000 5 共同` | 加上 `共同` = 兩人分攤：桶位只算你一半，DB 仍存全額。建立時會自動分類一次，每月產生的帳目直接繼承 |
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
| `/信件名單 [層] [頁] [搜尋]` | 信件整理每一層的名單（求職字眼 / 重視的公司 / 真人來信 / 你的規則 / 未知 / 各類別含求職 / 30 天內丟的）。不選層＝各層筆數總覽；每頁 25 筆、可搜尋寄件者與主旨；任何人都能看（只讀），ephemeral 回覆。唯讀，不動信件 |
| `/信件計畫` | 把目前的歷史信件整理計畫卡（各類別要加標籤／移出／丟幾封、範例主旨、待確認卡數、未知樣式數）發到信件頻道，並順便補發還沒成功發出過的確認卡；發送失敗會如實說。任何人都能下指令，但「🚀 執行歷史整理」鈕只有本人能按；計畫卡發出後才長出的確認卡不擋執行，但之後又確認卡或手動指定規則，舊的執行鈕會回「計畫已過期，請用 /信件計畫 重發」、一封都不動。每日整理在沒有待確認卡、目前這套已確認規則的計畫還沒成功發出過時也會自動發；執行中卡住也可以用它重發 |
