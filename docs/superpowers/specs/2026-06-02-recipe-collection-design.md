# 食譜收錄模組 設計規格（Recipe Collection）

- 日期：2026-06-02（2026-06-03 經多 agent 對照真實碼審核強化）
- 狀態：設計定稿（MVP），待實作計畫
- 作者：Johnny + Claude

## 1. 目標

讓使用者把喜歡的食譜連結「丟到 Discord 食譜頻道」，系統自動抽出**乾淨的菜名**存起來；之後自己煮飯時用 `/隨機食譜` 從庫裡抽一道，點開連結直接照做——解決「不知道今天要煮什麼、想一直變新花樣」。

核心策略：**食譜就是「一道菜 + 一個連結」**，不做餐廳那套地區/菜系正規化。最大化複用美食模組現成的連結抽取基礎建設（`food.extract` / `food.links`），只多一張表、一個菜名 prompt、三個指令。

## 2. 非目標（YAGNI）

- 不做分類（主食/湯/甜點）、不存食材清單——餐廳才需要分類，食譜不需要。使用者明確否決。
- 不追蹤「煮過/沒煮過」、不做評分心得——純隨機就滿足主場景，要再加。
- 不做食材搜尋（「我想用雞肉 → 抽雞肉食譜」）。
- 不做網頁清單頁（美食有地圖是因為要看地理分佈；食譜不需要）。
- 不做手動純文字新增食譜——食譜以連結為錨點；頻道內無連結的文字只當「改名 reply」或回提示。
- 不收 Google Maps 連結當食譜：`classify_platform` 會把 maps 連結標成 `gmaps`，而 `food.extract.from_url` 對 `gmaps` 回傳的是「店名」不是貼文 blob（`food/extract.py:173-179`）；食譜 ingest 直接略過 `gmaps`（見 §6.1）。

## 3. 與現有程式碼的接合與隔離（重點）

定位為「美食模組的瘦身兄弟」，自我內聚、不污染既有邏輯。複用點：

| 接合點 | 現況（已查證） | 本模組做法 |
|---|---|---|
| **連結偵測/分類** | `food.links.detect_links()` / `classify_platform()` / `strip_urls()`（純函式，子網域邊界比對防釣魚；`classify_platform` 可回 youtube/instagram/threads/tiktok/facebook/**gmaps**/other） | 直接 import 複用，**不重寫**；`gmaps` 在 ingest 略過（§6.1）。 |
| **連結 → 文字 blob** | `food.extract.from_url(url, platform)`：yt-dlp 主 + og fetch 備援，回 blob 或 **None** | 直接複用拿 blob，再餵自己的菜名 prompt（blob 可能 None，須 guard，見 §5）。 |
| **AI 文字解析** | `codex_cli.codex_text()`（訂閱制、純文字免計費） | 菜名抽取用 `codex_text` + 新 prompt。 |
| **資料表建立** | `main.py:25` `Base.metadata.create_all(bind=engine)` | **初次** `Recipe` 新表自動建立，無需 migration。**注意**：`create_all` 不會改既有表，日後若給 `Recipe` 加欄位/索引，需比照 `main.py:27-43` 手寫 `ALTER TABLE`（含 `UNIQUE(url)` 若分次上線）。 |
| **Discord `on_message` 分流** | 已有 `FOOD_INGEST_CHANNEL_ID` 分支 → `_handle_food_message`（`discord_handler.py:333-335`）後接「圖片附件分流」（336-360），`DISCORD_RECORD_CHANNEL_ID` 未設時會在**任意頻道**記帳（343-346） | 平行新增 `RECIPE_INGEST_CHANNEL_ID` 分支 → `_handle_recipe_message`，**緊接 food 分支之後、圖片附件分流之前**（§6.1），避免食譜訊息夾帶圖被記帳搶走。 |
| **卡片訊息 ID 回查** | `FoodPlace.discord_message_id` + `repo.set_message_id()` 目前**背的是 ✅-反應流程**：`on_raw_reaction_add`（`discord_handler.py:482-500`）→ `set_visited_by_message_id`（`repo.py:116`，依 `discord_message_id` 查並**順手改狀態**）。食譜的 reply-補件其實是另一條（`pending.get(ref.message_id)`，`discord_handler.py:381`），**不靠** `discord_message_id`。 | Recipe 新增 `discord_message_id` 欄位 + **新的純 getter** `recipe.repo.get_by_message_id()`（food.repo 無對應的純查版，只有會改狀態的 `set_visited_by_message_id`），給 **reply→改名** 用。這是新機制，非沿用。 |
| **需補件暫存** | `food.pending`（in-memory dict，module-level，key=`bot_message_id`，無 TTL；`remember(bot_message_id, *, original_message_id, ...)`） | 僅「連結抽不到菜名」少數情況複用**同一個全域 dict**；因 Discord message id 全域唯一，與美食卡片不會互撞（§6.2）。 |
| **多連結平行** | `asyncio.gather(*[asyncio.to_thread(ingest.from_url, ...)], return_exceptions=True)`，一連結一卡（`discord_handler.py:436-464`） | 完全比照（含 `return_exceptions=True`）。 |
| **Discord slash/embeds** | `_register_commands()`、`*_embed()`、`_post_embeds_sync()` | 同檔新增 3 個食譜指令與 embed builder，沿用既有風格/顏色。 |

新增程式集中在：`recipe/` 套件、`models.py`（一個 class）、`discord_handler.py`（一個頻道分支 + 一個 handler + 3 指令 + 3 embed）。**不動** `routes/`、不動記帳邏輯。

## 4. 資料模型

新增 ORM `Recipe`（`models.py`，沿用現有 `Column` 風格）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | Integer PK, index | 編號（slash 指令引用） |
| `name` | String, index | 乾淨菜名（codex 清理後；可被 reply 改名） |
| `url` | String, **unique**, index | 原始連結（**去重鍵**） |
| `platform` | String, nullable | `youtube`/`instagram`/`tiktok`/`facebook`/`threads`/`gmaps`/`other`（`classify_platform` 回傳，純標籤；`gmaps` 在 ingest 會被略過故實際少見） |
| `discord_message_id` | String, nullable, index | 卡片訊息 ID（給 reply 改名回查，見 §3/§6.2） |
| `created_at` | DateTime | `default=func.now()` |

**去重**：以 `url` 為唯一鍵。後端是 **PostgreSQL**（`DATABASE_URL=postgresql://…`），`UNIQUE(url)` 由 DB 交易強制。`add_recipe` 採 SELECT→INSERT，但**併發**下（同一則訊息含重複 url，或兩則訊息相近到達）兩個 thread 可能都 SELECT 不到、都 INSERT，後者會 `IntegrityError`——故 `add_recipe` 必須處理（見 §5）。

> 註：URL 去重採「原樣字串比對」。同一支影片的不同變體網址（帶不帶 `&t=`、`m.` 子網域）視為不同筆——可接受，避免引入脆弱的 URL 正規化。

## 5. 模組結構

```
recipe/
  __init__.py
  extract.py   # blob/文字 → 乾淨菜名（codex + 後處理；解析後處理可單測）
  repo.py      # Recipe DB 存取：add（url 去重+IntegrityError 防護）/ list / pick_random / delete / set_message_id / rename / get_by_message_id
  ingest.py    # 串接 links→extract.from_url→菜名→存 Recipe；回「成功卡」或「需補名」
```

`recipe/extract.py`：
- `_RECIPE_PROMPT`：要 codex「從內容抽出這道料理的菜名，去掉誇張標題/頻道名/emoji/集數，只回 `{"name":"..."}`；沒有回空字串」。
- `parse_name_json(raw)`（純函式，比照 `food.extract.parse_extracted_json` 的 markdown 去殼）。
- `name_from_text(text) -> str`：`codex_text(_RECIPE_PROMPT…)` → `parse_name_json`。

`recipe/ingest.py`：
- `from_url(url, *, caption="") -> tuple[dict|None, str]`：
  1. `platform = food.links.classify_platform(url)`；**若 `platform == "gmaps"` → 回 `(None, "這看起來是地點不是食譜，要收店家請丟 #🍜-美食")`**（不誤把店名當菜名）。
  2. `blob = food.extract.from_url(url, platform)`（**可能 None**）
  3. **guard None**（比照 `food/ingest.py:77`）：
     ```
     pieces = [p for p in (caption.strip() if caption else "", blob or "") if p]
     text = "\n".join(pieces)
     ```
  4. `text` 有內容 → `name = recipe.extract.name_from_text(text)`；`name` 仍空 → 退用 `blob` 第一行當暫定名；都空 → 回 `(None, "抽不到菜名")`（呼叫端要求 reply 補名）
  5. `rec, created = recipe.repo.add_recipe(name, url, platform)`；`rec["_created"]=created` → 回 `(rec, "")`

`recipe/repo.py`（比照 `food.repo` 的 `SessionLocal` 慣例 + `to_dict`）：
- `add_recipe(name, url, platform) -> (dict, created)`：先依 url SELECT；無 → INSERT。**INSERT/commit 包 `try/except IntegrityError`**：撞 `UNIQUE(url)` → `rollback` → 重新依 url SELECT → 回 `(existing, created=False)`。
- `list_recipes() -> list[dict]`（新到舊）
- `pick_random() -> dict | None`：**載入後 `random.choice`**（沿用 `food.recommend.pick_random`（`recommend.py:23`）的 random.choice 思路、純 Python 不用 SQL `random()`；差別：recipe 版自己 `list_recipes()` 載入、不收參數）；空回 None。
- `delete_recipe(id) -> bool`（True=刪了，False=查無）
- `set_message_id(id, message_id)` / `rename(id, new_name) -> dict | None`
- `get_by_message_id(message_id) -> dict | None`（**純 getter**，reply 改名回查；food.repo 無此純查版）

## 6. 流程

### 6.1 連結收錄（主軸）

`_handle_recipe_message` **僅當 `ch_id == RECIPE_INGEST_CHANNEL_ID` 時進入**（在 `on_message` 緊接 food 分支之後、圖片附件分流之前；故食譜訊息即使夾帶縮圖/圖片也不會被記帳搶走）。進入後依序：

```
1) reply（改名/補名）→ 見 §6.2（先處理）
2) links = detect_links(content)
   有連結：caption = strip_urls(content)
     → asyncio.gather(asyncio.to_thread(recipe.ingest.from_url, url, caption=caption) …, return_exceptions=True)  # 一連結一卡
     → 每筆：
         成功 → recipe_card_embed（🍳 菜名 · 📺 平台 · #編號 · 連結）→ set_message_id(rec.id, sent.id)
               （既存 created=False → 卡片標「你已收錄過」）
         gmaps/抽不到菜名 → recipe_missing_embed（含原因）；抽不到菜名者
               → pending.remember(sent.id, original_message_id=message.id, source_url=url)
3) 無連結、非 reply（純文字或純圖片）→ 回提示「這個頻道請丟食譜連結 🍳」（不記帳、不建檔）
```

### 6.2 改名 / 補名（reply，分支順序明確）

reply 一張卡片、打文字時，**依序**：

```
a) get_by_message_id(reference.message_id) 命中 Recipe → rename(id, reply文字) → 回更新後卡片
b) 否則 pending.get(reference.message_id) 命中（先前抽不到名）
     → 用 reply 文字 + pending.source_url 建 Recipe → 回卡片 → pending.consume
c) 兩者皆無（如 bot 重啟丟了 pending、或該 Recipe 已被 /食譜刪除 → message_id 變孤兒）
     → 回「這張卡片資料過期了，直接重貼連結就好」
```

> recipe 與 food 共用同一個全域 `food.pending` dict；因 Discord message id 全域唯一，recipe 卡片的 pending 永遠不會被 food handler 的 `pending.get` 取到、反之亦然，**無跨頻道互撞**。

### 6.3 隨機抽食譜（主場景）

```
/隨機食譜 → recipe.repo.pick_random() → recipe_random_embed（菜名 + 連結，點開照做）
          → 空庫 → 「還沒收錄任何食譜，先去 #🍳-食譜 丟幾個連結」
```

### 6.4 清單 / 刪除

```
/食譜清單        → list_recipes() → recipe_list_embed（編號 + 菜名 + 平台）
/食譜刪除 編號   → delete_recipe(id) → True 回「已刪除 #編號」/ False 回「找不到編號」
```

## 7. Discord 指令與 embed

新增 slash（沿用既有 `@tree.command` 中文命名慣例，先不限頻道）：
- `/隨機食譜`
- `/食譜清單`
- `/食譜刪除 編號`

新增 embed builder（比照 `food_*_embed` 風格與顏色常數）：
- `recipe_card_embed(rec, *, created=True)`
- `recipe_random_embed(rec)`
- `recipe_list_embed(recipes)`
- `recipe_missing_embed(reason)`（沿用 `food_missing_embed` 風格，或直接複用）

## 8. 錯誤處理

- **連結抽不到菜名 / blob 為 None** → 不崩潰，回「給我一句菜名」+ pending（§6.2）。
- **gmaps 連結** → 回「這是地點不是食譜」提示（§6.1），不建檔。
- **codex 失敗** → 比照現有顯示錯誤訊息（`error_embed`），不靜默吞。
- **多連結其中一個失敗** → 該連結回失敗卡，其餘照常（`gather(return_exceptions=True)`）。
- **reply 兩分支皆 miss**（重啟丟 pending／卡片已刪）→ 回「資料過期，直接重貼連結」（§6.2c）。
- **add_recipe 撞 UNIQUE(url)**（併發重複）→ rollback→re-SELECT→當「已收錄過」回，不噴 IntegrityError（§5）。

## 9. 測試

純函式走 pytest（比照 `tests/test_food_*`，無 DB/網路）：
- `recipe.extract.parse_name_json`：markdown 去殼、缺欄位補空、strip。
- `recipe.extract.name_from_text` 的後處理（mock codex 回應 → 乾淨名）。
- `ingest.from_url` 的 `gmaps` 略過、None-blob guard（mock `from_url`/`name_from_text`）。
- URL 去重 + IntegrityError 路徑：同 url 第二次 `add_recipe` → `created=False`（可記憶體 sqlite；併發路徑以單測模擬 IntegrityError 分支）。
- `pick_random`：空清單回 None、非空回其一。

`recipe.repo`（DB）、`food.extract.from_url`（網路）、Discord、codex 屬 I/O 邊界，不做單測。

## 10. 交付

單一階段即可上線（功能小）：
1. `Recipe` ORM + `recipe/` 套件 + 單測。
2. `discord_handler`：頻道分支（緊接 food 分支後、圖片分流前）+ `_handle_recipe_message` + 3 指令 + embed。
3. `.env` / `docker-compose.yml` 加 `RECIPE_INGEST_CHANNEL_ID`。
4. 依慣例：commit 同時更新 `README.md` 與 `CODEBASE.md`。

## 11. 環境變數（新增）

| 變數 | 說明 |
|---|---|
| `RECIPE_INGEST_CHANNEL_ID` | `#🍳-食譜` 頻道 ID；未設則食譜分支不啟用（不影響美食/記帳） |

## 12. 待確認 / 開放項目

- 菜名 prompt 的清理強度（要砍到多乾淨）：先寫一版，丟真實 YT/IG 連結實測再收斂。
- `pick_random` 是否要避免「連抽到同一道」：先純隨機，用過嫌重複再加最近排除。
- 多連結一次大量丟（少見）是否要限流：先比照美食不限（codex 成本比美食更低——食譜路徑不走 120s 的 `deep_extract_via_codex` 後援），真的洗版再加。
