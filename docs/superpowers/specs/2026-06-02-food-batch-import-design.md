# 美食批次匯入 設計規格（Food Batch Import）

- 日期：2026-06-02（2026-06-03 經多 agent 對照真實碼審核強化）
- 狀態：設計定稿（MVP），待實作計畫
- 作者：Johnny + Claude

## 1. 目標

使用者手機裡有「一堆店家名稱」（**markdown 待辦清單格式**，存在備忘錄/LINE），希望一次把整份匯進美食庫，不用一家一家 `/美食新增`。做法：**把清單多行貼進 `#🍜-美食` 頻道**，系統解析店名/地區 → Google 正名 → 入庫，最後回**一張智慧總結卡**（高信心/需確認/找不到分開列）。

實際清單長相（含勾選框前綴 + 尾端括號，括號可能沒收尾）：
```
- [ ] 鼎泰豐 (信義店)
- [x] 映客牛蒡天婦羅 (台中
- [ ] 這家拉麵超好吃 (台中)
```
- **勾選框**：`- [x]`（打勾）= 入庫標**去過**；`- [ ]`（沒勾）/無前綴 = **想去**。狀態直接帶入。
- **尾端括號**：內容**不一定**（有時地區/分店、有時心得）→ 交給 codex 判斷：是地區/分店填 `area`、是推薦菜填 `recommended_items`、純感想忽略。

核心策略：**直接匯入 + 智慧回報**（使用者明確選定，非「先預覽再確認」）。複用單筆 ingest 既有元件（`places.search_text` / `repo.upsert_place`），但**菜名解析改用「一次 codex 批次解析整份清單」**（而非逐行 N 次 codex，見 §6.1 理由），再逐行 Google 正名。

## 2. 非目標（YAGNI）

- 不做「先預覽配對結果、按 ✅ 才寫入」的互動確認流程（使用者選了直接匯入）。
- 不做檔案（.txt/CSV）上傳匯入——貼文字已覆蓋情境。
- 不做 Google 地圖收藏清單匯入（Takeout/GeoJSON）——若日後改用收藏清單會更準（零猜分店），屆時另開規格。
- 不做截圖批次（讀圖辨識多家）——本規格只處理純文字清單。
- 不為批次新增資料表/欄位——完全沿用 `FoodPlace`。
- **不走 `ingest.from_text` 逐行**：那條會額外做 `caution_for_place_id` 雷點加值（`food/ingest.py:51-58`，內含再一次 `codex_text`），批次 ×N 行成本翻倍。批次刻意**只** `search_text`+`upsert_place`（等同 `/美食新增`，`cmd_food_add` 也無雷點），不抓雷點摘要。

## 3. 與現有程式碼的接合與隔離（重點）

| 接合點 | 現況（已查證） | 本功能做法 |
|---|---|---|
| **頻道 ingest** | `_handle_food_message`：reply補件 → 圖片 → 連結 → 純文字（單行 `ingest.from_text`，`discord_handler.py:468-470`） | 在「純文字」分支內插入**批次偵測**：≥2 非空行 → 批次；單行維持單筆（完全相容）。 |
| **文字 → 欄位** | `food.extract.from_text(text)` → `{name, area, recommended_items, cuisine_type}`（codex，**單筆**） | **新增** `extract.parse_place_list(blob)`：一次 codex 把整份多行解析成**對齊行序的 list[fields]**（見 §6.1）。 |
| **行格式正規化** | 無（單筆 `from_text` 直接吃整串） | **新增**純函式 `strip_checkbox(line) -> (status, content)`：剝 `- [ ]`/`- [x]`/`-[x]`/`* [ ]` 等前綴，`[x]`→`去過`、否則→`想去`（§6.1 step 0，可單測）。 |
| **標去過** | `food.repo.set_visited(food_id, rating=None, note=None)` → `status="去過"`（`repo.py:72-89`） | `[x]` 行 upsert 後呼叫 `set_visited(p['id'])` 帶入去過（複用，不改 `upsert_place` 簽名）；**只升級不降級**（`[ ]` 不動既有去過）。 |
| **店名 → 正規店家** | `food.places.search_text(query)` → place dict 或 None | 逐行複用。 |
| **入庫去重** | `food.repo.upsert_place(place, *, recommended_items=None, cuisine_type=None, source_url=None)`（**keyword-only**），place_id 去重；**無** IntegrityError 防護（`repo.py:29-56`） | 逐行複用，但須先**在程序內依 place_id 去重**再 upsert（§6.1，避免併發 TOCTOU）。 |
| **平行處理** | 多連結 `asyncio.gather(*[asyncio.to_thread(...)])`（`discord_handler.py:436`，**無限流器**） | Google 正名逐行平行，**新增** `asyncio.Semaphore` 限流（net-new，非沿用；§6.4）。 |
| **刪除** | `food.repo` **目前無刪除**；slash 無 `/美食刪除`（已查證：`repo.py` 僅 upsert/list/set_visited/set_message_id/update_caution/set_visited_by_message_id） | **新增** `repo.delete_place(id) -> bool` + `/美食刪除 編號`（修正批次猜錯分店的手段）。 |

新增程式集中在：`food/extract.py`（`parse_place_list`）、`food/ingest.py`（批次 orchestrator）、`food/repo.py`（`delete_place`）、`discord_handler.py`（批次偵測分支 + 總結 embed + `/美食刪除`）。**不動**資料模型。

## 4. 資料模型

**無新增、無變更**。沿用 `FoodPlace`，批次匯入的每家等同單筆 `/美食新增`（`cmd_food_add`）：`status="想去"`、`place_id` 去重、`recommended_items`/`cuisine_type` 由 codex 帶入、**無雷點摘要**。

## 5. 觸發與判定

在 `#🍜-美食`（`FOOD_INGEST_CHANNEL_ID`）的訊息，於 `_handle_food_message` 內依序判定：

```
reply（命中 pending）        → 既有補件流程
有圖片附件                   → 既有圖片 ingest
有連結（detect_links 非空）  → 既有連結 ingest
─────────────────────────────────────────────
純文字：
  非空行數 ≥ 2  → 【新】批次匯入（§6）
  非空行數 == 1 → 既有單筆 from_text（完全相容）
```

> 判定只看「行數」這個低風險訊號：含連結/圖片的不會進來（前面分支先攔）；單行不受影響。**勾選框剝除只在批次路徑做**（單行 `from_text` 維持原樣）。
>
> **已知邊界**（§12）：(a) 一筆「店名 + 換行 + 一句註解/地址」的**單一店家跨兩行**輸入，會被誤判成 2 行批次（第 2 行的註解單獨送 → 多半 ❌ 找不到）。(b) **單獨一行** `- [ ] 店名` 貼進來（1 行）走單筆 `from_text`，**不會剝勾選框**。兩者對策相同：這種情況請改用 `/美食新增`，或日後把訊號改嚴（≥3 行、或排除「像同一句延續」的行）。

## 6. 批次流程

### 6.1 解析 → 正名 → 入庫

```
raw_lines = [非空白行] ; 取前 N 行（N ≤ 上限，§6.4）

# 0) 行正規化：剝勾選框前綴、帶出狀態（純函式 strip_checkbox，可單測）
#    "- [ ] 鼎泰豐 (信義店)" → ("想去", "鼎泰豐 (信義店)")
#    "- [x] 映客 (台中"      → ("去過", "映客 (台中")
#    "海底撈"（無前綴）       → ("想去", "海底撈")
parsed   = [strip_checkbox(l) for l in raw_lines]   # list[(status, content)]
contents = [c for _, c in parsed]

# 1) 一次 codex 批次解析（取代逐行 N 次 codex）
#    prompt 額外交代：每行尾端可能有括號（可能沒收尾），是地區/分店→area、是推薦菜→recommended_items、純感想忽略
fields_list = extract.parse_place_list(contents)   # 對齊行序：list[{name, area, recommended_items, cuisine_type}]，
                                                   #   無法解析的行回 {} / name=""

# 2) 逐行 Google 正名（平行 + 限流，見 §6.4）
async def _bounded(i):
    async with sem:                                # Semaphore 在 async 層，包住 await
        return await asyncio.to_thread(_resolve_one, i, fields_list[i], parsed[i], contents[i])
results = await asyncio.gather(*[_bounded(i) for i in range(len(contents))], return_exceptions=True)

# _resolve_one(i, fields, (status, _), content)（同步，在 thread 內跑）：
#   name 空                → ('failed', content)
#   place = search_text(f"{name} {area}".strip())
#     place None           → ('failed', content)
#     place 有             → 回 ('resolved', {place, fields, area_given: bool(area), status, raw: content})
#                            （此處先不 upsert，留到 §去重後統一寫，避免併發 TOCTOU）

# 3) 程序內依 place_id 去重後統一入庫 + 狀態（修 TOCTOU + 清單內重複店）
by_place = {}                                      # place_id → resolved（任一筆為去過則取去過：只升級不降級）
for r in resolved:
    cur = by_place.get(r.place['place_id'])
    if cur is None: by_place[r.place['place_id']] = r
    elif r.status == "去過": cur.status = "去過"
for r in by_place.values():
    p, _ = upsert_place(r.place, recommended_items=r.fields['recommended_items'] or None,
                        cuisine_type=r.fields['cuisine_type'] or None)
    if r.status == "去過":
        set_visited(p['id'])                       # 複用既有；只升級成去過，不動已是去過的
    分桶（§6.2，用 p['id'] 當 #編號、r.area_given 判信心、r.status 記想去/去過）
```

> **為何改一次批次 codex**：`extract.from_text` → `codex_text` 是 blocking subprocess、**timeout 180s**（`codex_cli.py:41`）。逐行 60 行 = 最多 60 個 subprocess，任何一行慢/卡會吃滿 slot。改成**一次** codex 解析整份（`codex_cli` 支援長 stdin），把 N 個 subprocess 收斂成 1 個；剩下只有 N 個 Google 呼叫（輕、由 semaphore 限流）。代價：單次解析多行的可靠度略低於逐行——故要求 codex 回**對齊行序的陣列**、解析不出的行回空 name（落 ❌，使用者看得到原文可重貼）。
>
> **為何先收集再 upsert**：`upsert_place` 以 SELECT→INSERT 去重、**無 IntegrityError 防護**（`repo.py:34-52`）。併發下兩行指向同一 `place_id`（清單重複店、或兩種寫法 Google 對到同一家）會雙 INSERT，後者撞 `place_id UNIQUE`（`models.py:50`）丟 `IntegrityError`，被 `return_exceptions=True` 吞成假 ❌。先在程序內依 place_id 去重、每個 place_id 只 upsert 一次，順帶解決「同店在清單出現兩次」重複計數。

### 6.2 信心分桶（核心 UX）

| 桶 | 條件 | 是否入庫 | 回報內容 |
|---|---|---|---|
| ✅ 高信心 | codex 抽到 `area`，**且** Google 回的店家有 `city`/`country`（`places.parse_address_components`） | 是 | 計數（預設不逐筆列店名，避免卡片過長） |
| ⚠️ 需確認 | Google 有配對，但 codex **無 `area`** 或 Google 回的店**無 city** | 是 | `#FoodPlace.id 原店名→Google正名` 逐筆列，供核對/修正 |
| ❌ 找不到 | codex 抽不到店名，或 Google 無配對，或該行例外 | 否 | 原始該行文字，供加地區重貼 |

> **誠實標註**：✅「高信心」是**啟發式**（依「codex 有給地區 + Google 有回地區」），**不等於** Google 配對一定正確——有地區仍可能對到錯分店。⚠️/✅ 只是把「最可能要人工核對的」挑出來，不是配對品質保證。分桶邏輯（given 每行 `(fields, place)` → 三桶）是可單測純函式。
>
> `#編號` = **`FoodPlace.id`**（`upsert_place` 回的 `to_dict(rec)` 含 `id`，`repo.py:9`），正是 `/美食刪除 編號` 吃的鍵、也是單筆卡片 footer 用的編號（`discord_handler.py:230`）。因 upsert 去重，既有店回的是舊 id，**id 不保證連號**（§6.3 範例已避免假連號）。

### 6.3 回報（單張總結卡，不洗版）

`food_batch_summary_embed(buckets)` 一張 embed：

```
批次匯入完成（共 18 行 · 想去 13 / 去過 2）
✅ 高信心 12 家（已入庫）
⚠️ 需確認 3 家（沒地區或 Google 沒給城市，請核對）：
   · #112 鼎泰豐 → 鼎泰豐 信義店
   · #47 映客 → 映客牛蒡天婦羅
❌ 找不到 2 家（加上地區再重貼）：
   · 「這家拉麵超好吃」
   · 「××××」
（已略過 1 行空白；超過 60 行未處理：N 行 ← 只有截斷才顯示）
```

> 標題的「想去/去過」來自勾選框（§6.1）：`- [x]` 的店標去過、其餘想去。

**不靜默截斷**：若行數超過上限，明確標示「未處理 N 行，請分批再貼」。

### 6.4 護欄

- **單則訊息上限 60 行**：超過只處理前 60，總結卡明講未處理行數。
- **平行限流**（**net-new，非沿用**——既有多連結 `gather` 並無限流器，`discord_handler.py:436`）：`asyncio.Semaphore(約 5–8)` 包在 **async 層**（`async with sem: await asyncio.to_thread(...)`，見 §6.1 `_bounded`），限制同時在飛的 Google 正名數。Semaphore **不可**放進 `_resolve_one` 同步函式體內（sync thread 無法 `async with` asyncio 物件）。
- **成本模型**：批次 = **1 次 codex 批解析** + **N 次 Google search_text**（N≤60，semaphore 限 5–8 同時）。限流是為 bound Google 呼叫量；codex 已收斂成單次故非瓶頸。
- **去重**：程序內先依 place_id 去重再 upsert（§6.1）；與既有庫重複則 `upsert_place` 更新不新增。

### 6.5 修正手段

⚠️ 猜錯分店 / 不要的 → `/美食刪除 編號`（吃 `FoodPlace.id`）砍掉 → `/美食新增 店名 區域` 帶地區重加。`/美食刪除` 為本功能新增（§7）。

## 7. Discord 指令與 embed

- 新增 slash：`/美食刪除 編號`（`@app_commands.describe(編號="店家編號")` → `repo.delete_place(編號) -> bool` → True 回「已刪除 #編號」/ False 回「找不到編號 N」）。
- `repo.delete_place(food_id: int) -> bool` 契約：刪到回 True、查無回 False（與 `set_visited` 的 dict-or-None 風格不同，因刪除只需成功/失敗布林）。
- 新增 embed：`food_batch_summary_embed(buckets)`（沿用既有顏色/風格）。
- 批次偵測與呼叫寫在 `_handle_food_message` 純文字分支內、單行判斷前。

## 8. 錯誤處理

- **某行 codex 解析不出 / Google 例外** → 該行歸 ❌（附原文），不影響其他行（`return_exceptions=True`）。
- **整批 codex 服務掛掉**（`parse_place_list` 丟例外）→ 整批回一句「解析失敗：{訊息}」，不假裝成功。
- **upsert 撞 place_id UNIQUE**（理論上已被 §6.1 程序內去重擋掉；防禦性仍可在 `upsert_place` 加 IntegrityError→re-query）→ 不靜默吞成假 ❌。
- **配額/網路失敗** → 記 log + 該行 ❌。
- **空訊息/全空白行** → 不進批次，無動作。

## 9. 測試

純函式走 pytest（無 DB/網路）：
- **行數判定**：`splitlines` + 去空白 → 是否觸發批次（1 行 vs ≥2 行 vs 含空白行）。
- **`strip_checkbox`**：`- [ ]`/`- [x]`/`-[x]`/`* [ ]`/無前綴 → 正確 `(status, content)`；`[x]`→去過、其餘→想去；尾端括號**原樣保留**給 codex（含沒收尾的 `(台中`）。
- **上限截斷**：>60 行 → 取前 60 + 回報未處理數。
- **分桶純函式**：given 每行 `(fields, place)` 結果 → 正確落入 ✅/⚠️/❌（含「有地區但 Google 無 city → ⚠️」）。
- **place_id 程序內去重 + 狀態升級**：兩行對到同一 place_id → 只 upsert 一次、不重複計數；其一為 `[x]` → 該店標去過（只升級不降級）。

`extract.parse_place_list`（codex）、`places.search_text`（Google）、`repo`（DB）、Discord 屬 I/O 邊界，以薄封裝隔離，不做單測。

## 10. 交付

單一階段：
1. `food.extract.parse_place_list(lines) -> list[fields]`（一次 codex 批解析）+ `food.ingest.strip_checkbox(line) -> (status, content)`（純函式）。
2. `food.ingest.batch_from_text(blob) -> buckets` orchestrator + 分桶/截斷/place_id 去重+狀態純函式 + 單測。
3. `food.repo.delete_place(id) -> bool`（`set_visited` 已存在，直接複用帶去過）。
4. `discord_handler`：批次偵測分支 + `food_batch_summary_embed` + `/美食刪除`。
5. 依慣例：commit 同時更新 `README.md` 與 `CODEBASE.md`。

## 11. 環境變數

無新增（沿用 `FOOD_INGEST_CHANNEL_ID`）。

## 12. 待確認 / 開放項目

- 上限 60 行是否合適：依實際清單長度調整（codex 已收斂成單次，主要看單張卡片可讀性與 Google 配額）。
- 「店名+換行+註解」的多行單店會被誤判批次（§5）：先以「請改用 `/美食新增`」吸收；嫌煩再把批次訊號改嚴。
- ✅ 高信心是否逐筆列店名：預設只給計數；需要再展開。
- 分桶訊號要不要再強化（如比對「Google 回的店名 vs 輸入名」相似度）：先用「area + Google city」啟發式。
- 日後若改用 Google 地圖收藏清單匯入（更準、零猜分店），另開規格。
