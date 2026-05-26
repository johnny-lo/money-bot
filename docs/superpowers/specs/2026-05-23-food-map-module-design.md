# 美食地圖模組 設計規格（Food Map Module）

- 日期：2026-05-23
- 狀態：設計定稿（MVP 導向），待 Phase 0 事前清單 + 實作計畫
- 作者：Johnny + Claude

## 1. 目標

讓使用者把喜歡的美食影片/截圖「丟到 Discord 美食輸入頻道」，系統自動整理成一筆店家，並提供：

1. **縣市/國家推薦**：輸入「我想去台中 / 日本」，列出該地尚未去過的店家（含隨機挑一家）。
2. **地圖**（MVP 後）：標出所有店家，以顏色區分「想去 / 去過」。

核心策略：**先做出「真的會想用」的 MVP，之後沒在用的模組再慢慢刪**。MVP 以「截圖 → 自動抽取 → 入庫 → 推薦」為主軸；能自動抽就自動填，抽不到就用 Discord reply 補件。

## 2. 非目標（YAGNI）

- 不做 yt-dlp 下載影片 + 抽幀辨識（維護成本高、踩平台 ToS）。改用「截圖 + caption 文字」覆蓋實際情境。
- 不寫入使用者的 Google Maps 原生清單（公開 API 不支援）。
- 不做多使用者/權限系統：清單為**單一共用清單**（情侶共用），`my_rating`/`my_note` 不分人。
- 不做訂位、菜單價格爬取。
- pending（需補件）**不做過期清理 / 垃圾回收**——單人低頻率不需要。

## 3. 與現有程式碼的接合與隔離（重點）

此模組定位為「額外模組」，自我內聚、不污染現有記帳邏輯。接合點如下：

| 接合點 | 現況 | 本模組做法 |
|---|---|---|
| **Discord `on_message`** | 對**任何頻道**的圖片附件都當「拍照記帳」 | 改頻道分流（見 §3.1）。**關鍵防撞**：避免美食截圖被誤記成支出。 |
| **資料表建立** | `main.py` 用 `Base.metadata.create_all(bind=engine)` | 新增 `FoodPlace` ORM 後新表自動建立，無需手動 migration。 |
| **HTML 報表/Token** | `auth.py` 的 `generate_report_token(user_id)` / `require_token`（泛用 30 分鐘 token） | 地圖網頁（MVP 後）直接重用。 |
| **路由** | `routes/report.py`、`routes/record.py` 用 `APIRouter` + `include_router` | 地圖階段新增 `routes/food_map.py` 同樣掛載。 |
| **AI 文字解析** | `codex_cli.codex_text()`（訂閱制） | 解析店名/品項/類型、摘要負評用 `codex_text`（純文字、免計費）。 |
| **AI 影像辨識** | `gemini.gemini_image()` | 截圖讀字用既有 `gemini_image`。 |
| **Discord slash/embeds** | `discord_handler._register_commands()`、`*_embed()`、`_post_embeds_sync()` | 同檔新增美食指令與 embed builder，沿用既有風格與顏色常數。slash 先不限制頻道。 |

新增程式集中在：`food/` 套件、`models.py`（一個 class）、`discord_handler.py`（分流 + 指令）；地圖階段才加 `routes/food_map.py`、`templates/food_map.html`。

### 3.1 Discord `on_message` 頻道分流（含防呆退路）

```
圖片/訊息進入 on_message
  ├─ channel == FOOD_INGEST_CHANNEL_ID  → 美食 ingest（圖片/網址/文字/reply 補件）
  ├─ channel == DISCORD_RECORD_CHANNEL_ID → 既有圖片記帳 handle_image_data()
  ├─ DISCORD_RECORD_CHANNEL_ID 未設     → 【退路】維持舊行為：任何頻道圖片都記帳
  │                                        （並於啟動時印警告，避免靜默關掉記帳）
  └─ 其他頻道收到圖片                   → 不記帳，回一句指引：
                                          「記帳請丟 #記帳，記美食請丟 #美食輸入」
```

> 退路設計是記取教訓：先前「channel ID 漏帶 → 靜默失敗」。本模組**寧可退回舊行為也不靜默關閉**既有記帳。
>
> 指引提示只對**圖片**觸發，且**同頻道一段時間內只提示一次**（防洗版），避免每則訊息都被回。

### 3.2 LINE / Discord 分工

| 入口 | 用途 |
|---|---|
| LINE | 無腦快速記帳，尤其圖片記帳/發票/明細。 |
| Discord `#記帳`（`DISCORD_RECORD_CHANNEL_ID`） | Discord 內圖片記帳入口。 |
| Discord `#美食輸入`（`FOOD_INGEST_CHANNEL_ID`） | 美食收件匣：截圖、網址、文字、補件 reply。 |
| Discord slash commands | 查詢/管理/推薦/地圖/標去過；先不限頻道。 |

## 4. 資料模型

新增 ORM `FoodPlace`（`models.py`，沿用現有 `Column` 風格；`lat/lng` 需 `Float`）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | Integer PK | 編號（slash 指令引用） |
| `name` | String, index | 正式店名（Google Places 回傳正名） |
| `address` | String | 完整地址 |
| `lat` / `lng` | Float, nullable | 座標（地圖用；MVP 推薦不需要） |
| `place_id` | String, index, unique | Google Place 唯一 ID（去重 + 導航連結） |
| `country` | String, index | 國家（**一定有**；國外可用此粒度查全部） |
| `city` | String, nullable, index | 城市（**有就填、不限台灣**；台灣=縣市，國外=locality/administrative_area，如 東京/大阪/首爾） |
| `district` | String, nullable | 區（有就存，沒有不強求） |
| `cuisine_type` | String, nullable, index | 料理類型（拉麵/咖啡…；AI 推測，可空、可改；先自由文字） |
| `recommended_items` | String, nullable | 推薦品項（文字） |
| `caution_summary` | String, nullable | **雷點提醒**：Google 低星負評 AI 摘要（取代平均星等，見 §6.4） |
| `status` | String | `想去`（預設）/ `去過` |
| `my_rating` | Integer, nullable | 共用評分（標去過時填，1–5；不分人） |
| `my_note` | String, nullable | 共用心得（不分人） |
| `source_url` | String, nullable | 原始影片/貼文連結存證 |
| `discord_message_id` | String, nullable, index | 卡片訊息 ID（給 ✅ 反應回查對應店家） |
| `created_at` | DateTime | 記錄時間，`default=func.now()` |
| `updated_at` | DateTime | 最後更新時間，`default=func.now(), onupdate=func.now()`（重複丟同店時更新，用於「最近又丟過這家」） |

**去重**：以 `place_id` 為唯一鍵；同一家重複丟 → 更新（補來源/品項/時間）+ 回「這家你已記過」提示（見 §6.7），不新增重複。

### 4.1 地區規則（推薦的命脈）

- 查 Places 一律帶 `languageCode=zh-TW`，讓 `country`/`city` 回中文。
- `country` 一定填；`city` **有就填、不限台灣**（台灣=縣市；國外盡量存 locality/administrative_area，如 東京/大阪/首爾）。國外既可按國家查（列全部）也可按城市縮小。
- **推薦比對**：使用者輸入一個詞，同時比對 `country` 與 `city`，用「正規化 + 別名 + 包含」而非精確等於：
  - 台灣縣市別名：`台中 = 台中市 = Taichung`、`台北 = 台北市 = Taipei`…
  - 國家別名：`日本 = Japan`、`韓國 = Korea`…
  - 國外城市別名：`東京 = Tokyo`、`大阪 = Osaka`、`首爾 = Seoul`…（別名表持續補；查不到精確就退包含比對）
  - 找不到精確 → 退而用包含比對。
- 別名/正規化是純函式，納入單元測試。

## 5. 模組結構

```
food/
  __init__.py
  extract.py     # 截圖/文字/連結 → {店名, 區域提示, 推薦品項, 類型}（純解析後處理，可單測）
  places.py      # Google Places API (New)：Text Search 找店 + Place Details 抓評論
  recommend.py   # 依 country/city（含別名正規化）篩選 + 排序「想去」+ 隨機挑一家（純函式，可單測）
  pending.py     # 需補件狀態（in-memory dict，key=bot_message_id，無 TTL）
  ingest.py      # 串接 extract → places → 雷點摘要 → 存 FoodPlace；回「成功卡片」或「需補件卡片」
routes/food_map.py      # （地圖階段）GET /food/map（HTML, token）、/api/food/places（JSON, token）
templates/food_map.html # （地圖階段）Google Maps JS 前端
```

`discord_handler.py` 內新增：
- `on_message` 頻道分流（§3.1）
- `on_raw_reaction_add`：在 `#美食輸入` 對卡片按 ✅ → 查 `discord_message_id` → `status=去過`，並回一句「要記評分/心得嗎？回我一句或用 `/去過`」
- slash：`/美食推薦 <縣市或國家>`、`/去過 <編號> [評分] [心得]`、`/美食清單`、`/美食新增 <店名> [區域] [推薦品項]`（後路用）、（地圖階段）`/美食地圖`
- embed builder：`food_place_embed()`、`food_missing_embed()`、`food_reco_embed()`

## 6. 流程

### 6.1 截圖自動接收（MVP 主軸）

```
在 #美食輸入 丟截圖
  → on_message（channel == FOOD_INGEST_CHANNEL_ID）
  → food.extract：gemini_image 讀畫面文字 → codex_text 解析 {店名, 區域提示, 推薦品項, 類型}
  → food.places：用店名(+區域) 查 Places (New) Text Search → 正規店家(地址/座標/place_id/country/city)
  → food.places：抓 Place Details 評論 → 低星摘成 caution_summary（§6.4）
  → food.ingest：存 FoodPlace(status=想去)；place_id 已存在則更新（§6.7）
  → 回「店家卡片」embed（店名/類型/地址/推薦品項/⚠️雷點/Google 連結），記 discord_message_id
    └─ 缺店名 / Places 找不到 → 回「⚠️ 需補件」卡片 → 進 pending（§6.3）
```

### 6.2 手動新增（後路，非主角）

知道店名、懶得截圖時用：

```
/美食新增 店名 [區域] [推薦品項]
  → 同 6.1 的 places → 雷點摘要 → 存 FoodPlace → 回卡片
```

### 6.3 需補件（Discord reply）

```
bot 貼「⚠️ 需補件」卡片
  → food.pending 建記憶體記錄（key = bot_message_id）：
      original_message_id / raw_text / source_url / attachment_url / missing_reason
  → 使用者 reply 這張卡片（例：「台中 某某拉麵」）
  → on_message 讀 message.reference.message_id → 查 pending
  → 併入補的店名/區域 → 重查 Places → 存 FoodPlace → 回卡片 → 刪 pending
  → 查不到 pending（如 bot 重啟過）→ 回「這張卡片資料過期了，直接重貼店名/地址就好」
```

> pending 用 in-memory dict（比照 `auth.py` token store），**不做 TTL/GC**；重啟遺失可接受。

### 6.4 雷點摘要（取代平均星等）

理由：美食影片已經讓你想去了，真正缺的是**反向情報**。

```
加店時 → Places Place Details 取 reviews（每家約 5 則「最相關」）
  → 篩出低星（≤ 3 星）的評論文字
  → codex_text 摘成一句「⚠️ 雷點提醒：…」存 caution_summary
  → 若 5 則內沒低星 → 寫「近期評論沒看到明顯雷點」
```

限制：Places 每家只回約 5 則評論、不保證涵蓋所有負評；這是 best-effort 參考，不是完整負評分析。

**實作原則（事後加值）**：雷點摘要需**額外一次 Place Details 呼叫**，會增加幾秒延遲。所以**先把店存成功、回卡片**，雷點摘要當事後加值補上（可同步補或背景補）；任一段（評論/摘要）失敗或太慢都**不影響、不拖慢入庫**，`caution_summary` 留空即可。

### 6.5 標記去過

- **✅ 反應**：對卡片按 ✅ → `on_raw_reaction_add` → 依 `discord_message_id` 找店 → `status=去過` → 回「要記評分/心得嗎？」
- **slash**：`/去過 <編號> [評分1-5] [心得]` → `status=去過` + 寫 `my_rating`/`my_note`

### 6.6 縣市/國家推薦

```
/美食推薦 台中   → recommend 比對 city（含別名）+ status=想去 → embed 清單
/美食推薦 日本   → recommend 比對 country（含別名）+ status=想去 → embed 清單
  → 清單含店名/類型/推薦品項/⚠️雷點/Google 連結
  → 附「🎲 隨機挑一家」：站在路口選擇困難時直接給一家
  → 純查自家 DB，不呼叫 Google
```

### 6.7 重複提醒

丟到已存在的店（同 place_id）→ 不靜默更新，回：「🍜『X』你 3 週前記過了（狀態：想去）」，順手更新來源/品項/時間。低頻率下你會忘記記過，這個防呆很有感。

## 7. 外部 API 與費用護欄

| API | 用途 | 觸發時機 | 免費額度 |
|---|---|---|---|
| Google Places API (New) — Text Search | 店名 → 正規店家 | 每記一家新店 1 次 | 依 Google Maps Platform free cap，實作前確認 |
| Google Places API (New) — Place Details（含 reviews） | 抓評論做雷點摘要 | 每記一家新店 1 次 | 較高階 SKU、免費額度較小（約 1,000/月），個人用量仍免費；實作前確認 |
| Google Maps JavaScript API — 動態地圖 | 地圖網頁（地圖階段才用） | 每次開地圖 1 次 | 依 free cap，實作前確認 |
| Geocoding（備用） | 純地址 → 座標 | 多半用不到（Places 已給座標） | 依 free cap |
| YouTube Data API（選填，連結階段） | YouTube 標題+簡介 | 每支 YouTube 連結 | 免費配額 |

**費用護欄（必做）：**
- **MVP 只需一把後端 key**：`GOOGLE_PLACES_SERVER_KEY`，用 API restrictions 限定只允許 Places API (New)。**不放進任何前端 HTML**。
- **Browser key（`GOOGLE_MAPS_BROWSER_KEY`）到地圖階段才申請**，用 HTTP referrer 限定固定 ngrok 網域 + 限定只允許 Maps JavaScript API（前端必然曝光，故 referrer 鎖定是必須）。
- Google Cloud Console 設**配額硬上限**：Places ≤ 50/日、（地圖）Maps 載入 ≤ 200/日。
- 設預算警示：帳單 > US$1 即 email。
- 結論：個人用量預期 **US$0/月**；配額/key 限制是護欄而非絕對保證。

> 啟用前提：Google Cloud 專案需綁帳單帳號（信用卡）才能開 key，免費額度內不扣款。屬一次性設定，詳見 Phase 0 清單。

## 8. 錯誤處理（human-in-the-loop）

- **截圖/連結抽不到店名 / Places 找不到** → 不崩潰，貼「需補件」卡片走 §6.3；多候選則回清單請 reply 編號。
- **配額達上限 / API 失敗** → 記 log + 回明確訊息（沿用「⚠️ …失敗：{訊息}」風格），不靜默吞掉。
- **AI（codex/gemini）失敗** → 比照現有顯示錯誤訊息。
- **雷點摘要失敗** → `caution_summary` 留空，不擋整筆入庫。
- **非目標頻道誤丟圖片** → 不記帳，回指引（§3.1）。

## 9. 測試

純函式走 pytest（比照 `tests/test_report_helpers.py`，無 DB/網路）：
- `food.extract`：辨識/caption 文字 → 解析店名/品項/類型的後處理。
- `food.recommend`：清單 + 查詢 → 正確篩選（僅想去）、別名正規化（台中=台中市、日本=Japan）、隨機挑一家。
- 地址 component → `country/city/district` 正規化。
- `food.pending`：給 `bot_message_id` / reply 內容 → 正確找到 pending 並產生補件資料。

`food.places`（Google）、Discord、AI 屬 I/O 邊界，不做單測；以薄封裝隔離。

## 10. 分階段交付（MVP 先行，之後刪沒用的）

| 階段 | 內容 | 交付後可用 |
|---|---|---|
| **Phase 0** | 事前清單（§11）：建 `#美食輸入`、確認 `#記帳` ID、Google Cloud 綁帳單、開 Places server key、設配額+預算、填 env。**全手動，無 code** | 環境就緒 |
| **Phase 1（MVP）** | 頻道分流 + 截圖自動 ingest（extract→Places→雷點摘要→存→卡片）+ ✅/reply 補件 + `/去過` + `/美食推薦`（含隨機）+ `/美食清單` + `/美食新增`(後路) | **截圖記店、出門前查推薦——第一個真的會用的版本** |
| **Phase 2** | 地圖網頁（browser key + Maps JS + token）+ `/美食地圖` | 地圖看想去/去過 |
| **Phase 3（選）** | 連結來源：YouTube（官方 API）→ IG/TikTok/FB（caption 盡力 + 降級補件） | 直接貼連結 |
| **Prune** | 用過 MVP 後，回看哪些指令/欄位沒在用 → 刪 | 模組保持精簡 |

每階段獨立可用、可單獨驗收。

## 11. Phase 0 事前清單（寫 code 前逐項打勾）

- [ ] 建 Discord `#美食輸入` 頻道，複製 channel ID → `FOOD_INGEST_CHANNEL_ID`
- [ ] 確認/補上 `#記帳` channel ID → `DISCORD_RECORD_CHANNEL_ID`
- [ ] Google Cloud：建專案、綁帳單帳號
- [ ] 開後端 key → `GOOGLE_PLACES_SERVER_KEY`，API restrictions 限「Places API (New)」
- [ ] 設配額硬上限（Places ≤ 50/日）+ 預算警示（> US$1 email）
- [ ] 把以上填進 `.env`
- [ ] 同步加進 `docker-compose.yml` 的 `environment:`（避免容器內 `os.getenv()` 拿不到）
- [ ] （地圖階段才做）開 browser key、限 ngrok 網域

> 完整逐步操作指引（含 Google Cloud 點哪裡）在進入 Phase 0 時提供。

## 12. 環境變數（新增）

| 變數 | 何時需要 | 說明 |
|---|---|---|
| `FOOD_INGEST_CHANNEL_ID` | MVP | `#美食輸入` 頻道 ID |
| `DISCORD_RECORD_CHANNEL_ID` | MVP | `#記帳` 頻道 ID；未設則退回「任意頻道記帳」+ 警告 |
| `GOOGLE_PLACES_SERVER_KEY` | MVP | 後端 Places (New)；限 Places API、不入前端 |
| `GOOGLE_MAPS_BROWSER_KEY` | 地圖階段 | 前端 Maps JS；限 ngrok referrer |
| `YOUTUBE_API_KEY` | 連結階段（選） | YouTube 標題+簡介 |
| `FOOD_COMMAND_CHANNEL_ID` | 選填 | 未來要限制美食 slash 頻道再加 |
| `BASE_URL` | 地圖階段 | 產地圖連結用；可順手取代程式裡硬寫的 ngrok domain |

## 13. 待確認 / 開放項目

- 推薦排序：預設「最近記錄優先」；是否加「雷點少的優先」等加權，用過再定。
- 料理類型：先自由文字，量大再考慮收斂成封閉清單。
- `caution_summary` 是否要定期刷新（評論會變）；MVP 先只在加店時抓一次。
- `BASE_URL` 是否順手整理現有報表連結一起改用 env。
