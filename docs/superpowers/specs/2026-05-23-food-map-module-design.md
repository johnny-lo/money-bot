# 美食地圖模組 設計規格（Food Map Module）

- 日期：2026-05-23
- 狀態：設計定稿，待實作計畫
- 作者：Johnny + Claude

## 1. 目標

讓使用者把喜歡的美食影片/貼文「丟給機器人」，自動記錄成一筆店家，並提供兩種呈現：

1. **地圖**：在地圖上標出所有店家，以顏色區分「想去 / 去過」。
2. **縣市/國家推薦**：輸入「我想去台中 / 日本」，從清單推薦尚未去過的店家。

核心精神：**半自動（human-in-the-loop）**——能自動抽取就自動填，抽不到或信心不足就回頭請使用者補資訊。系統永遠可用，差別只在自動化程度。

## 2. 非目標（YAGNI）

- 不做 yt-dlp 下載影片 + 抽幀辨識（維護成本高、踩平台 ToS）。改用「caption 文字 + 截圖」覆蓋實際情境。
- 不寫入使用者的 Google Maps 原生清單（公開 API 不支援）。
- 不做多使用者/權限系統（沿用單人 bot 現況）。
- 不做訂位、菜單價格爬取、社群留言分析。

## 3. 與現有程式碼的接合與隔離（重點）

此模組定位為「額外模組」，盡量自我內聚、不污染現有記帳邏輯。接合點如下：

| 接合點 | 現況 | 本模組做法 |
|---|---|---|
| **Discord `on_message`** | `discord_handler.py` 目前對**任何頻道**的圖片附件都當「拍照記帳」 | **必須依 `message.channel.id` 分流**：等於 `FOOD_CHANNEL_ID` → 走美食抽取並 `return`；否則維持原拍照記帳。這是避免「截圖被誤記成支出」的關鍵防撞。 |
| **資料表建立** | `main.py` 用 `Base.metadata.create_all(bind=engine)` | 新增 `FoodPlace` ORM 後，新表會自動建立，無需手動 migration。 |
| **HTML 報表/Token** | `auth.py` 的 `generate_report_token(user_id)` / `require_token` 為泛用一次性 token（30 分鐘） | 地圖網頁**直接重用**，不另造輪子。 |
| **路由** | `routes/report.py`、`routes/record.py` 用 `APIRouter`，在 `main.py` `include_router` | 新增 `routes/food_map.py`，於 `main.py` `include_router(food_map_router)`。 |
| **AI 文字解析** | `codex_cli.codex_text()`（訂閱制） | 解析店名/品項/類型用 `codex_text`（純文字、免計費）。 |
| **AI 影像辨識** | `gemini.gemini_image()` | 截圖讀字用既有 `gemini_image`。 |
| **Discord slash/embeds** | `discord_handler._register_commands()`、各 `*_embed()` builder、`_post_embeds_sync()` | 在同檔新增美食指令與 embed builder，沿用既有風格與顏色常數。 |

不更動現有記帳/報表/發票邏輯；新增程式集中在 `food/` 套件、`routes/food_map.py`、`templates/food_map.html`、`models.py`（新增一個 class）、`discord_handler.py`（新增分流與指令）。

## 4. 資料模型

新增 ORM `FoodPlace`（`models.py`，沿用現有 `Column` 風格；`lat/lng` 需 `Float`）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | Integer PK | 編號（slash 指令引用） |
| `name` | String, index | 正式店名（Google Places 回傳正名） |
| `address` | String | 完整地址 |
| `lat` / `lng` | Float | 座標（畫地圖） |
| `place_id` | String, index, unique | Google Place 唯一 ID（去重 + 導航連結用） |
| `country` | String, index | 國家（Places address component） |
| `city` | String, index | 縣市（administrative_area / locality） |
| `district` | String, nullable | 區（locality / sublocality） |
| `cuisine_type` | String, nullable, index | **料理類型**（拉麵 / 咖啡 / 火鍋…；AI 推測，可空、可手動修） |
| `recommended_items` | String, nullable | 推薦品項（文字） |
| `status` | String | `想去`（預設）/ `去過` |
| `my_rating` | Integer, nullable | 自己的評分（標去過時填，1–5） |
| `my_note` | String, nullable | 心得 |
| `google_rating` | String, nullable | Google 評分（參考） |
| `source_url` | String, nullable | 原始影片/貼文連結存證 |
| `discord_message_id` | String, nullable, index | 卡片訊息 ID（給 ✅ 反應回查對應店家） |
| `created_at` | DateTime | 記錄時間，`default=func.now()` |

**去重**：以 `place_id` 為唯一鍵；同一家重複丟，更新而非新增（並可補上來源連結）。

## 5. 模組結構

```
food/
  __init__.py
  extract.py     # 連結/截圖 → {店名, 區域提示, 推薦品項, 類型}（純解析邏輯，可單測）
  places.py      # Google Places client：店名(+區域) → 正規店家(地址/座標/place_id/region/評分)
  recommend.py   # 依 country/city 篩選 + 排序「想去」清單（純函式，可單測）
  ingest.py      # 串接 extract → places → 存 FoodPlace；回傳「成功卡片」或「缺資訊卡片」資料
routes/food_map.py     # GET /food/map（HTML, 需 token）、GET /api/food/places（JSON, 需 token）
templates/food_map.html # Google Maps JS 前端
```

`discord_handler.py` 內新增：
- `on_message` 的美食頻道分流（呼叫 `food.ingest`）
- `on_raw_reaction_add`：在美食頻道對卡片按 ✅ → 查 `discord_message_id` → 狀態改「去過」
- slash：`/美食推薦 <縣市或國家>`、`/去過 <編號> [評分] [心得]`、`/美食地圖`、`/美食清單`
- embed builder：`food_place_embed()`、`food_missing_embed()`、`food_reco_embed()`

## 6. 流程

### 6.1 接收與抽取

```
使用者在 #🍜-美食地圖 丟「連結」或「截圖」
  → on_message 偵測 channel == FOOD_CHANNEL_ID
  → food.extract 取原始資訊：
       - YouTube 連結  → YouTube Data API 取標題+簡介 → codex_text 解析
       - IG/TikTok/FB 連結 → 嘗試讀 caption → codex_text 解析；失敗則標記「需補件」
       - 圖片附件      → gemini_image 讀畫面文字 → codex_text 解析
  → 得到 {店名, 區域提示, 推薦品項, 類型}
  → food.places 用店名(+區域) 查 Google Places Text Search → 正規店家
  → food.ingest 存 FoodPlace(status=想去)；place_id 已存在則更新
  → 貼「店家卡片」embed（店名/類型/地址/推薦品項/Google 連結），記下 message_id
    └─ 缺店名 / Places 找不到 → 貼「⚠️ 需補件」卡片，請使用者回覆店名或地址
```

### 6.2 標記去過

- **方式一**：對卡片按 `✅` → `on_raw_reaction_add` → 依 `discord_message_id` 找店 → `status=去過`。
- **方式二**：`/去過 <編號> [評分1-5] [心得]` → 設 `status=去過` 並寫 `my_rating`/`my_note`。

### 6.3 地圖呈現

- `/美食地圖` → `generate_report_token(user_id)` → 回 `{BASE_URL}/food/map?token=...`（30 分鐘）。
- 網頁載入 Google Maps JS，向 `/api/food/places?token=...` 取 JSON，畫 marker：
  - `想去` = 藍 pin、`去過` = 綠 pin
  - 點 marker → info window：店名 / 類型 / 推薦品項 / 心得 / 原連結 / 「Google 導航」連結（用 place_id）

### 6.4 縣市/國家推薦

- `/美食推薦 台中` 或 `/美食推薦 日本` → `food.recommend` 查 DB：`(city == X or country == X) and status == 想去` → embed 清單（店名/類型/推薦品項/Google 連結）。
- 純查自家 DB，**不呼叫 Google**。附「在地圖看這區」連結（地圖頁可吃 `?focus=台中` 之類參數，Phase 2 視情況做）。

## 7. 外部 API 與費用護欄

| API | 用途 | 觸發時機 | 每月免費額度 |
|---|---|---|---|
| Google Places API — Text Search | 店名 → 正規店家 | 每記一家新店 1 次 | 5,000 |
| Google Maps JavaScript — 動態地圖 | 地圖網頁 | 每次開地圖 1 次 | 10,000 |
| Geocoding（備用） | 純地址 → 座標 | 多半用不到（Places 已給座標） | 10,000 |
| YouTube Data API（選填，Phase 4） | YouTube 標題+簡介 | 每支 YouTube 連結 | 免費配額 |

**費用護欄（必做，寫入設定步驟）：**
- Google Cloud Console 設**配額硬上限**：Places Text Search ≤ 50/日、Maps 載入 ≤ 200/日（達上限直接擋，物理上打不出免費額度）。
- 設預算警示：帳單 > US$1 即 email 通知。
- 結論：個人用量實際成本 **US$0/月**，且配額上限保證不會因程式錯誤暴衝。

> 啟用前提：Google Cloud 專案需綁定帳單帳號（信用卡）才能開 API key，免費額度內不扣款。屬一次性設定（約 5 分鐘），實作時提供逐步指引。

## 8. 錯誤處理（human-in-the-loop）

- **連結平台抓取脆弱**：IG/TikTok/FB 讀 caption 失敗 → 不報錯崩潰，改貼「需補件」卡片請使用者補店名/地址或補張截圖。
- **Places 找不到 / 模糊**：回前幾個候選讓使用者選，或請補更完整店名/區域。
- **配額達上限 / API 失敗**：記 log + 回覆明確訊息（沿用現有「⚠️ …失敗：{訊息}」風格），不靜默吞掉。
- **AI（codex/gemini）失敗**：比照現有作法顯示錯誤訊息。

## 9. 測試

純函式走 pytest（比照 `tests/test_report_helpers.py` 風格、無 DB/網路）：
- `food.extract`：給定 caption/辨識文字 → 解析出店名/品項/類型的後處理邏輯（可解析的部分）。
- `food.recommend`：給定店家清單 + 查詢縣市/國家 → 正確篩選與排序、僅含「想去」。
- 地址 component → `country/city/district` 的正規化函式。

`food.places`（Google）、Discord、AI 呼叫屬 I/O 邊界，不做單測；以薄封裝隔離。

## 10. 分階段交付

| 階段 | 內容 | 交付後可用 |
|---|---|---|
| **Phase 1** | 頻道分流 + 截圖辨識 + Places 解析 + 存 `FoodPlace` + 店家卡片 + 需補件流程 + `✅`/`/去過` | 截圖記店、標去過 |
| **Phase 2** | 地圖網頁（Maps JS API + token）+ `/美食地圖` | 地圖看想去/去過 |
| **Phase 3** | `/美食推薦 <縣市/國家>` + `/美食清單` | 縣市/國家推薦 |
| **Phase 4（選）** | 連結來源：YouTube（官方 API）→ IG/TikTok/FB（caption 盡力 + 降級） | 直接貼連結 |

每階段獨立可用、可單獨驗收。

## 11. 環境變數（新增）

| 變數 | 說明 |
|---|---|
| `FOOD_CHANNEL_ID` | Discord 美食頻道 ID（on_message 分流用） |
| `GOOGLE_MAPS_API_KEY` | Places + Maps JS 共用（建議在 Console 限制 API 與來源） |
| `YOUTUBE_API_KEY` | 選填，Phase 4 用 |
| `BASE_URL` | 產地圖連結用（若現有報表已有可重用） |

需同步加入 `docker-compose.yml` 的 `environment:`（比照先前 channel ID 漏帶導致靜默失敗的教訓）。

## 12. 待確認 / 開放項目

- 推薦清單排序規則：預設「最近記錄優先」，未來可加 Google 評分加權（Phase 3 再定）。
- 地圖 `?focus=<region>` 聚焦參數是否要做（Phase 2 視需要）。
- 料理類型是否要收斂成封閉清單（如分類那樣）或自由文字（先自由文字，量大再收斂）。
