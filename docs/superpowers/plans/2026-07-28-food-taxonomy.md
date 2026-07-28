# 美食地圖：料理兩層分類 + 行政區細化

## Context

美食地圖現在的分類顆粒度太粗，兩個面向都不堪用：

**地區**：`city` 被 `canon()` 砍後綴 → 桃園市/新竹市/新竹縣全糊成「桃園」「新竹」，**新竹市(11筆) 和新竹縣(10筆) 完全分不出來**，竹北/竹東根本無法辨識。`district` 欄位存的是**里名**（興南里、普仁里，105/112 筆），毫無用處；只有 3 筆是真行政區，7 筆是 NULL。而且 city 目前有**三種格式並存**（`台北市` 全名、`桃園` 去後綴、`臺東` 去後綴且用臺）。

**料理**：`cuisine_type` 是 LLM 自由填的文字，112 筆裡 30 筆空白、82 筆散成 **49 種**不同寫法，從「咖啡」到「費城起司牛肉三明治」到毫無資訊的「小館」「食堂」「餐廳」。沒有受控詞彙表 = 沒有可用的篩選軸。

**目標**：料理走兩層（12 個受控大類 + 自由細類），地區細到鄉鎮市區（桃園市中壢區 / 新竹縣竹北市 / 新竹縣竹東鎮）。**這輪不做車程**（起點是即時 GPS，無法預存，另案處理）。

好消息：`address`（Google formattedAddress，zh-TW）112 筆全有，且含真正的行政區（`320台灣桃園市中壢區興南里永樂街97號`）→ **整批回填零 Google API 呼叫**。

---

## 全域決策（先定，後面每步都靠它）

**D1｜`city` 不變式**：一律 22 個台灣縣市**全名、台不用臺**（`桃園市`/`新竹縣`/`新竹市`/`台北市`/`台東縣`）。國外城市維持現況開放詞彙。

**D2｜不動 `canon()`**。`canon()` 是 `region_matches` 的**模糊比對鍵**，不是儲存格式。改它會直接弄死 `/美食推薦 桃園`。儲存格式用新的 `normalize_city()`。已驗證：`canon("桃園市")→"桃園"`、`canon("新竹縣")→"新竹"`、`canon("台北市")→"台北市"`（別名命中）——現有查詢全部照常。

**D3｜`district` 不變式**：屬於該縣市的合法鄉鎮市區，或 NULL。**永不是里/村**。用封閉查表保證，不靠 regex 形狀猜。

**D4｜台灣地址以 `address` 文字為單一真相**。實證：同樣兩個縣市，Google 對 id 57 給「平鎮區」、對 id 36 給 NULL；對 id 83 給「北區」、對 id 89(竹東鎮)/103(竹北市) 給 NULL。**光改 `parse_address_components` 優先序會留下 7 筆 NULL，且救不回竹北市/竹東鎮**。`addressComponents` 只負責 `country` + 國外地址（日/韓路徑一字不動）。

**D5｜料理三欄**：新增 `cuisine_major`（大類，12 選 1）+ `cuisine_minor`（細類），**`cuisine_type` 原封不動留著當原始稽核文字**。好處：回填只寫新欄 → 零遷移風險、完全可逆（`SET cuisine_major=NULL, cuisine_minor=NULL` 就回去了）、規則改良後可整批重推；且**舊的 PWA 殼（service worker 快取）照常運作**，不會因為 key 改名整排卡片副標空白。

**D6｜判不出就是空字串**，不設「其他」桶。空欄誠實且可查（`WHERE cuisine_major IS NULL`），「其他」會永久混淆「真的其他」和「規則沒中」。UI 在顯示層渲染成「其他」。

**D7｜12 大類詞彙表只住在 `food/cuisine.py` 一個地方**。**不寫進 `food/extract.py` 的四個 LLM prompt**——兩份詞彙表必然漂移，且 LLM 幻覺值會直接進 DB。prompt 繼續產自由文字 `cuisine_type`，大類一律由 `classify()` 推導。規則改良 → 重跑回填就整批重新分類。

**大類（12，使用者已定案）**：日式、韓式、中式、台式、東南亞、西式、火鍋、燒烤、早午餐、咖啡甜點、飲料冰品、酒吧餐酒館
**落類規則**：菜系國別優先於品類（日式燒肉→日式+燒肉，不是燒烤）。已定案的爭議條目：印度咖哩→東南亞、牛肉麵→台式、費城三明治→西式。

---

## 實作步驟

### Task 0 — spec 落檔
依 AGENTS.md §8 的流程，把上面的 Context + D1~D7 寫成 `docs/superpowers/specs/2026-07-28-food-taxonomy-design.md` 並 commit（純設計文件，豁免 README/CODEBASE 更新規則）。

### Task 1 — `food/tw_divisions.py`（純資料，新檔）
```python
TW_CITIES: tuple[str, ...]                    # 22 個縣市，台-form
CITY_ALIASES: dict[str, str]                  # 臺北市/桃园市/Taipei City → 正名
TW_DISTRICTS: dict[str, tuple[str, ...]]      # 縣市 → 鄉鎮市區，共 368 個
DISTRICT_ALIASES: dict[str, dict[str, str]]   # 逐縣市的升格舊名
                                              # 桃園市: 中壢市→中壢區, 平鎮市→平鎮區, 八德市→八德區,
                                              #         楊梅市→楊梅區, 蘆竹鄉→蘆竹區, 大溪鎮→大溪區…
                                              # 新北市: 板橋市→板橋區, 三重市→三重區…
```
把 368 筆表格獨立成一個檔，`regions.py` 的「純函式、無 I/O」定位才不會被資料淹掉。
測試：`sum(len(v) for v in TW_DISTRICTS.values()) == 368`。

### Task 2 — `food/regions.py` 地址 parser（TDD）
新增純函式，複用既有 `to_traditional()`（L34）：
```python
def normalize_city(s) -> str                          # 任意寫法 → 22 縣市全名；非台灣回 ""
def normalize_district(city, s) -> str                # 該縣市的合法鄉鎮市區，否則 ""
def parse_tw_address(addr) -> tuple[str|None, str|None]
def resolve_region(address, components) -> dict       # 唯一入口，D4 的優先序住這
```
**演算法**（兩個 agent 都實測過，這是收斂版）：
1. 折字：既有 `_S2T`（簡→繁）+ **另一張** `臺→台` 表（方向相反，別跟 `_S2T` 混在一起，下一個讀的人會搞錯）。
2. **縣市**：在 `TW_CITIES ∪ CITY_ALIASES` 掃**最左出現**、同位取**最長**。用全名比對天然解掉 `新竹縣竹北市` 不含 `新竹市`。
3. **行政區（正向）**：取縣市 token 之後的字串，對 `TW_DISTRICTS[city] ∪ DISTRICT_ALIASES[city]` 做**錨定在 index 0 的最長前綴比對**。
4. **行政區（倒向）**：正向沒中才跑，取縣市之前的字串做最長後綴比對（英文倒序地址）。
5. **輸出查表的正規字串，不是比中的原文** —— 簡體/臺/舊名的差異在此結構性消失。
6. 非台灣（country ≠ 台灣）**完全不進這條路徑**。

**為什麼錨定比對打敗 regex**：`300台灣新竹市東區南市里勝利路131號` —— 錨定在 index 0 只會比中「東區」，永遠碰不到「南市」；任何 `[區鄉鎮市]` 掃描式 regex 都會吃成「東區南市」（agent 實測重現過）。

**改 `parse_address_components`（L77-104）**：簽名加 `*, address=None`；台灣分支先試 `parse_tw_address`，拿不到才退回 components（city 走 `normalize_city` 不再過 `canon`；district 若 `endswith(("里","村"))` 直接丟掉，寧可 NULL）。**國外分支一字不動**（`locality > aal1 > aal2` 過 `canon()`，district 用 sublocality）→ 現有 Tokyo 測試（`tests/test_food_regions.py:46-55`）保持綠。
呼叫端 `food/places.py:54` 改成傳 `address=p.get("formattedAddress")`。

**改 `region_matches`（L65）**：加 `district=None` 參數（預設 None，呼叫端沒改也不炸）+ 三條規則：
1. 全名精確命中 country/city/district → True
2. query 自帶「市/縣」後綴（使用者明確指定）→ 只認全名（`/美食推薦 新竹市` 不再撈到新竹縣）
3. 否則 canon 後互相包含（沿用舊行為，多比一個 district）→ `/美食推薦 中壢` 開始命中 `district=中壢區`、`竹北`→`竹北市`

`food/recommend.py:12` 加 `p.get("district")`；`discordbot/commands.py:186` 的說明改成「縣市/鄉鎮市區/國家，例如 中壢 / 新竹市 / 日本」。
**順手修掉的既有 bug**：`/美食推薦 台東` 現在回空（`canon("臺東")="臺東"` vs `canon("台東")="台東"` 比不中），D1 統一成台-form 後自動修好——加一條測試釘住。

### Task 3 — `food/cuisine.py`（TDD，新檔）
```python
MAJORS: tuple[str, ...]   # 12 個，順序即 UI chips 順序
def normalize_major(s) -> str                                    # 別名折疊 + 詞彙表檢查；不在表內回 ""
def classify(raw, *, name="", items="") -> tuple[str, str]       # (major, minor)
```
規則：
1. 正規化 raw（strip、簡→繁、全形→半形、ASCII 轉小寫），對 `、，,/／|・` 和空白切 token。
2. 丟掉 `_JUNK` 封閉集合（小館/食堂/餐廳/餐館/料理/家常料理/美食/小吃店/專賣店/店）；全是垃圾就當空、落到第 4 步。
3. **最左關鍵字命中者勝，同位國別勝**。這一條就等於「菜系國別優先」——中文的國別修飾語必在名詞前，agent 在 112 筆真實資料上驗證 100% 成立，比「先掃國別表再掃品類表」的兩階段更簡單也更可預測。`日式燒肉`→日式、`韓式燒肉`→韓式、`美式BBQ燒烤`→西式、`咖啡、早午餐`→咖啡甜點、`燒肉`（無國別）→燒烤。
4. **所有關鍵字 ≥2 字**（不准有單字「日」「韓」「泰」），否則店名「日日排骨」誤命中。
5. `minor` = 清洗後的 raw 去掉命中的國別前綴（`日式燒肉`→`燒肉`、`泰式料理`→`""`、`咖啡、早午餐`→原樣保留多 token）。
6. raw 推不出才退到 `name` + `recommended_items`，用**另一份更窄、更高精度**的關鍵字表（中文沒有詞界，`和食` 會在「平和食品」誤命中）；此時 `minor` 只放命中的關鍵字，**不從菜單捏造細類**。
7. 都不中 → `("", "")`（D6）。

必測的陷阱（agent 從真實資料挖到的）：`肉球尼尼` 的 items 是 `起司牛排漢堡、番茄燉雞歐姆蛋、中式煎餅、魚漢堡` —— 「國別優先」若寫成兩階段會誤判成**中式**（漢堡店！），最左命中才正確給西式。

**覆蓋率實測**：關鍵字表吃掉 89/112；剩 23 筆中約 18 筆可由店名/推薦菜規則解決（`極清拉麵`→日式、`是吉祥精緻火鍋館`→火鍋、`五燈獎豬腳飯`→台式…），真正無訊號的只剩 4-5 筆（`拾旅。食`、`KAORI Dining`、`十平`…）→ 留 NULL 或事後手補，**不需要 LLM**。

### Task 4 — schema（`models.py` + `main.py`）
`models.py` FoodPlace 加兩欄（註解寫死語意）：
```python
cuisine_major = Column(String, index=True, nullable=True)  # 大類（12 選 1，見 food/cuisine.MAJORS）
cuisine_minor = Column(String, nullable=True)              # 細類（拉麵/牛肉麵/法式甜點）
# cuisine_type 保留＝LLM 原始自由文字，稽核用，不再直接顯示
```
`create_all` 不會動既有表（AGENTS.md §3）→ 在 `main.py:35-63` 的 inspector 區塊加 `food_places` 段（照 `food_photos` FK 那段的形狀），`ADD COLUMN` + `CREATE INDEX IF NOT EXISTS`，並 `print("✅ …")`。
⚠️ `main.py:62-63` 把所有失敗吞成 `print("⚠️ …")` → ALTER 失敗會靜默，然後 SQLAlchemy 每次 food 查詢都 `SELECT cuisine_major` 炸掉。重啟後**必須** `docker logs money-bot | grep -E '✅|⚠️'` 確認。

### Task 5 — 寫入路徑收斂到單一咽喉點（`food/repo.py`）
`city`/`district`/`cuisine_*` 只有三個寫入者，全部經過 `upsert_place`（`discordbot/commands.py:180`、`food/ingest.py:47`、`food/ingest.py:275`）→ **正規化放在 `upsert_place` 裡面，不放呼叫端**，混格式列就結構性不可能出現：
```python
rec.country, rec.city, rec.district = regions.normalize_region(place)   # 冪等
if cuisine_type:                        # 沿用「有值才蓋」
    rec.cuisine_type = cuisine_type
    maj, minr = cuisine.classify(cuisine_type, name=place["name"], items=recommended_items or "")
    if maj: rec.cuisine_major = maj     # 永不用空字串蓋掉既有值
    rec.cuisine_minor = minr
```
**順手修既有的資料流失 bug**：`food/repo.py:42-45` 目前無條件覆寫 country/city/district —— 一次退化的 Places 回應（缺 addressComponents）就把好資料抹成空。加「非空不被空覆寫」的守衛。
`to_dict`（L6-26）加兩個新欄。

### Task 6 — 回填 `food/backfill_food_taxonomy.py`（照 `food/enrich.py:46-86` 的形狀）
**純規劃器 + 薄寫入器**，規劃器可單測、不連 DB：
```python
plan_region_rows(rows)  -> list[Change]   # 純函式
plan_cuisine_rows(rows) -> list[Change]   # 純函式
Change = {id, name, address, field, old, new, source, ok, reason}   # source: addr/components/raw/name/items
run(kind, *, dry_run=True, mode="missing", force=False)
verify_invariants()      # 全表掃描，印出任何越界值
restore_from(path)
```
安全機制（112 筆 → 人工目視 diff 是這裡最強的控制，報表要設計成「給人讀」而非「給人略過」）：
- **dry_run 預設 True**，diff 依 `(old → new)` 分組（`桃園 → 桃園市 ×57` 只佔一行，3 筆倒序地址才會跳出來）。
- **第一次寫入前備份**到 `.backups/food_taxonomy_pre_<YYYY-MM-DD-HHMM>.json`（沿用既有 `.backups/` 慣例），含 `{id, place_id, city, district, cuisine_type, cuisine_major, cuisine_minor}`。
- **中止閘**：任何台灣列解不出 city → 除非 `force=True` 否則拒絕寫入。
- 逐列 try/except + **逐列 commit**（`database.session_scope()`）→ 第 57 列爆炸不影響前 56 列，重跑會跳過已完成的。
- **冪等**：目標欄位與現值相同就跳過 → **第二次跑必須印 `0 changed`，這是冪等的證明，是必做步驟不是選配**。
- `mode="missing"`（預設，只補空）vs `mode="rules"`（規則改良後整批重推，仍不用空覆寫非空）。

跑法（AGENTS.md：一律 docker exec）：
```bash
docker exec -w /app money-bot python -c "from food.backfill_food_taxonomy import run; run('region', dry_run=True)"
# 目視 diff → 沒問題才 dry_run=False → 再跑一次確認 0 changed → verify_invariants()
```
⚠️ AGENTS.md §3：這是情侶共用的**正式 DB**，寫入前先跑 dry-run 並告知使用者。

### Task 7 — 讀取端
| 檔案 | 改動 |
|---|---|
| `food/map_data.py:20-36` | payload 加 `district`、`cuisine_major`、`cuisine_minor` |
| `discordbot/embeds.py:190-193` | 類型＝`大類 · 細類`（都空才 fallback `cuisine_type`）；地區＝`country / city / district` |
| `discordbot/embeds.py:214` | 清單一行內優先顯示大類（要短） |
| `templates/food_map.html:150` | 同步 |

**前端**（`frontend/src/`）：
- `Food.jsx`：新增 `district`、`major` 兩個 state。縣市 select 排序（現在是 `created_at DESC` 的亂序）；行政區 select **依選中的縣市衍生**，且**換縣市時必須 `setDistrict('all')`**——否則選了中壢區再換台北市會永遠空清單且毫無解釋；沒有行政區就不 render。大類 chips 依 `MAJORS` 固定順序，但**只留資料裡真的有的**（不出現永遠 0 筆的死 chip）。L47-49 的 filter 擴成四條件。
- 版面：`.food-bar` 現在是單列（`index.css:45-49`），12 個 chip 塞不下 → 加第二列 `.chips.scroll { overflow-x:auto }`。⚠️ `index.css:132` 的 `.map-error { top: 66px }` 是寫死「篩選列只有一列」的偏移量，多一列要一起調。
- `FoodList.jsx:4-14`：`CUISINE_ICON` 改成 12 大類**精確比對** `cuisine_major`，**保留舊的 substring map 當 fallback**（沒 major 的店照舊有 icon）。card-sub 顯示 `📍 city district · 大類 · 細類`。
- `PlaceSheet.jsx:86` 同步。

### Task 8 — 測試（純函式，照 AGENTS.md §6）
- **新 `tests/test_food_tw_address.py`**：把 112 筆真實地址存成 fixture，property 式掃描 —— `city ∈ TW_CITIES`、`district ∈ TW_DISTRICTS[city] | {None}`、`district` 永不以里/村結尾、parser 冪等。再逐條釘住陷阱：新竹市 vs 新竹縣（id 79/82）、縣轄市竹北市/竹東鎮（82/89/103）、里名同形（`東區南市里`85、`竹北市竹北里`95、`中壢區中壢里`45）、簡體+升格舊名 `中坜市`（69）、**三筆**英文倒序（17/31/78）、`臺東縣臺東市`（102）、村（109）、6 位郵遞區號（118）、尾端垃圾（61）、國外地址不進 TW parser、`None`/空字串。
- **擴 `tests/test_food_regions.py`**：釘住 D2（`region_matches` 在全名下仍然全中：桃園/新竹/台北/**台東**）、`resolve_region` 地址優先於 components、components 解不出時的退路。**必改**：L88 的 `assert out["city"] == "桃園"` → `"桃園市"`。
- **新 `tests/test_food_cuisine.py`**：國別優先（日式燒肉/韓式燒肉/美式BBQ燒烤/法式甜點/義式冰淇淋）、複合值（咖啡、早午餐／甜品、豆花、仙草、飲品／肉圓、大腸麵線、臭豆腐）、咖哩＝咖喱、垃圾值（小館/食堂/餐廳）→ `("","")`、**肉球尼尼漢堡店陷阱**、店名 fallback、`normalize_major` 對幻覺值一律回 `""`（fuzz 不變式）、爭議條目（麵食/冰室/鐵板燒/豆花/印度咖喱/重慶麻辣火鍋）釘死而非留模糊。
- **新 `tests/test_food_backfill_taxonomy.py`**：只測純規劃器（已正規的列 → `[]`、`桃園`+`興南里` → 2 個 Change、解不出的台灣地址 → `ok=False` 且 `run()` 無 force 會中止、絕不產生「空覆寫非空」的 Change、`mode="missing"` 跳過已有值的列）。
- **必改 `tests/test_food_map_data.py:61-64`**：精確 key set 斷言 → 加三個新 key。

---

## 上線順序（每一步 app 都是活的）

1. **Task 1-3**（純函式 + 測試，沒人 import）→ `pytest` 全綠。零行為改變。
2. **Task 4**（schema）→ `docker exec -w /app money-bot python -c "import main"` → `docker restart money-bot` → 輪詢等 `Application startup complete`（開機發票同步會塞 30-90s，curl 回 000 是正常）→ `docker logs | grep ✅` 確認欄位建好。
3. **Task 5**（寫入路徑）→ 新列開始正規化，舊列不動，所有讀取端仍寬容 → `/美食新增` 用真店家 smoke（⚠️ 會寫進共用正式 DB，挑可刪的並告知使用者）。
4. **Task 6**（回填）→ dry-run 讀 diff → 備份 → 寫入 → **重跑確認 0 changed** → `verify_invariants()` → SQL 抽驗 3 筆倒序列（17/31/78）+ 21 筆新竹列。
5. **Task 7**（讀取端）→ `pytest` → `npm run build --prefix frontend` → curl 確認伺服器送新 bundle → curl `/api/food/places`（用 DB device token，記憶體 token 跨行程無效）確認有 `district` → **手機視覺交使用者親眼確認**（AGENTS.md §4：無自動化視覺測試，不可自稱修好）。
6. **README.md + CODEBASE.md**（專案鐵律），順手更 `docs/architecture.html` 的欄位清單。

**順序的理由**：schema → 寫入 → 回填 → 讀取。先回填後改寫入，中間任何一次 Discord 匯入都會無聲地重新污染那一列；先改讀取後回填，使用者會看到混格式。

---

## 驗證

```bash
docker exec -w /app money-bot python -m pytest tests/ -q          # 全綠
docker exec -w /app money-bot python -c "import main" && echo OK   # import 預檢
docker exec money-db psql -U user -d money_db -c \
  "SELECT city, district, count(*) FROM food_places GROUP BY 1,2 ORDER BY 1,2;"   # 目視：無里名、新竹縣市已拆
docker exec money-db psql -U user -d money_db -c \
  "SELECT cuisine_major, count(*) FROM food_places GROUP BY 1 ORDER BY 2 DESC;"   # 目視：12 類 + NULL
DTOK=$(docker exec -w /app money-bot python -c "from database import SessionLocal; from models import DeviceToken; s=SessionLocal(); t=s.query(DeviceToken).order_by(DeviceToken.id.desc()).first(); print(t.token if t else 'NONE'); s.close()")
curl -s -H "X-Device-Token: $DTOK" -H "ngrok-skip-browser-warning: true" http://127.0.0.1:8000/api/food/places | head -c 400
```
Discord 端：`/美食清單` 看 embed、`/美食推薦 中壢`（新增的 district 命中）、`/美食推薦 台東`（修好的 bug）、`/美食推薦 新竹市`（不該撈到新竹縣）。
PWA：篩選列兩排、縣市→行政區級聯、大類 chips —— **使用者親眼確認**（PWA 有 SW 快取，可能要重開 1-2 次才接管）。

---

## 關鍵檔案

新增：`food/tw_divisions.py`、`food/cuisine.py`、`food/backfill_food_taxonomy.py`
修改：`food/regions.py`、`food/repo.py`、`food/places.py`、`food/map_data.py`、`food/recommend.py`、`models.py`、`main.py`、`discordbot/embeds.py`、`discordbot/commands.py`、`frontend/src/{Food,FoodList,PlaceSheet}.jsx`、`frontend/src/index.css`、`templates/food_map.html`
**不動**：`food/extract.py` 的四個 LLM prompt（D7 —— 詞彙表只有一份）、`canon()`（D2）、`parse_address_components` 的國外分支（D4）

## 風險

- **PWA 快取**是這個 repo 的頭號誤判來源：後端多回 key 舊殼會忽略（不炸），但新篩選 UI 要重開 1-2 次才看得到 → 先 curl 驗伺服器端再說。
- **368 筆行政區表**是手寫資料，有打錯字風險 → 靠 `sum == 368` 和「112 筆真實地址全部解得出且在詞彙表內」兩條測試守住。
- **國外店目前 0 筆**，國外分支是唯一沒有真實資料可驗的路徑 → 只能靠現有 Tokyo 單元測試守住，所以那條路徑一字不改。
