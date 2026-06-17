# 歷史教學影片模組 — 設計 spec

- 日期：2026-06-17
- 分支：feat/mobile-pwa-frontend
- 狀態：設計定稿，待寫實作計畫（writing-plans）

## 目的

新增第四個「頻道模組」🎥 歷史教學影片：在專屬 Discord 頻道丟 YouTube（等）連結
→ AI 自動判主題與標籤 → 在 Discord 或手機 PWA 整理 → 之後依分類瀏覽 / 標籤搜尋找回影片。

定位：**個人（情侶兩人共用）的結構化影片圖書館**。沿用既有「食譜」模組的連結收集骨架，
資料層多加一個這專案還沒有的多對多（標籤）模式。

## 已定決策（brainstorming 結論，不再重議）

1. **連結收集器，非檔案儲存**：只存 URL + metadata，不下載/不存影片檔。沿用現成 yt-dlp，
   零儲存成本。（排除了上傳影片檔的方案。）
2. **使用情境**：主要是「按分類瀏覽」+「標籤/關鍵字搜尋」。
   *不做* 課程進度追蹤、*不做* 拉霸隨機抽（使用者未勾，YAGNI）。
3. **組織模型 = 方案 A：主分類 + 多標籤**
   - 主分類 `topic`：一支影片只屬於一個，是瀏覽用的「書架」。
   - 標籤 tags：一支影片可掛多個，是跨分類搜尋用的索引。
4. **標籤表用「去正規化」**：`video_tags` 直接存標籤字串（非另開 tags 表 + 關聯表）。
   理由：兩人用 + LLM 自動產生標籤，重複/改名風險低，簡單性收穫大，與專案現有風格一致
   （`food_places.city` 也是直接存字串）。若日後標籤需統一改名，再升級為正規化（獨立、低風險重構）。
5. **三層編輯工作流（同一個 repo，三個薄客戶端）**：
   - ① AI 首判（丟連結當下，全自動）
   - ② Discord 回覆卡片（順手微調，**輕量**）
   - ③ 網頁 PWA（事後整理，**主力編輯器**）
   三層都只是呼叫同一組 `video_repo` 函式，標籤的「真相」只存在 `video_tags` 表一處。
6. **Discord 回覆語法 = 增量 +/-**（非整包覆蓋）：見下方語法規格。
7a. **「越笨越好」的提示（不用記語法）**：每張卡片底部固定印「回覆小抄」，回覆時說明就在輸入框正上方；
    另外打 `help` / `?` / 任何看不懂的純文字都直接回同一張小抄。見 §2 的「②.5 求助/提示」。
7. **YouTube 縮圖免費用**：`https://img.youtube.com/vi/<id>/hqdefault.jpg`，零儲存零 API 成本。
   非 YouTube（如 B 站）退回 emoji 墊底（與食譜清單同一 fallback 模式）。

## 1. 資料模型（models.py 新增兩張表）

```python
class HistoryVideo(Base):
    __tablename__ = "history_videos"
    id        = Column(Integer, primary_key=True, index=True)
    title     = Column(String, index=True)               # yt-dlp 抓標題，LLM 清乾淨
    url       = Column(String, unique=True, index=True)   # 去重鍵（同連結 = 同影片）
    topic     = Column(String, nullable=True, index=True) # 主分類 / 書架（一支一個）
    channel   = Column(String, nullable=True)             # 講師/頻道名（yt-dlp uploader）
    platform  = Column(String, nullable=True)             # youtube / bilibili / other
    discord_message_id = Column(String, nullable=True, index=True)  # 回覆修正用
    created_at = Column(DateTime, default=func.now())

class VideoTag(Base):
    __tablename__ = "video_tags"
    id       = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("history_videos.id", ondelete="CASCADE"),
                      index=True, nullable=False)
    tag      = Column(String, index=True, nullable=False) # 去正規化：直接存標籤字串
```

- 查「掛某標籤的影片」= `WHERE tag = ?`；列出所有標籤 = `SELECT DISTINCT tag`。
- 刪影片時 `ondelete="CASCADE"` 連帶刪掉它的 `video_tags` 列。
- 兩張全新表，由 `main.py:28` 的 `Base.metadata.create_all` 開機自動建，**不需 migration**。
  （只有「改既有表結構」才要手動補，如 main.py:47 的 food_photos FK。）

## 2. 攝取 + 編輯工作流

### ① AI 首判（攝取）

流程沿用 `recipe/ingest.py` + `food/extract.py` 的 yt-dlp 抓取：

```
handle_video_message(url)
  1. classify_platform(url)            # 既有：youtube / bilibili / other
  2. food.extract 的 yt-dlp 抓 title / uploader(channel) / description（沿用，metadata-only）
  3. LLM 一次吐 {topic, tags[]}：
       codex_text(_VIDEO_PROMPT.format(text=title+description)) → parse JSON
       （prompt 要求：topic 給單一最貼切主題；tags 給 3~5 個跨切標籤；都用繁中）
  4. video_repo.add_video(title, url, topic, channel, platform) → (dict, created)
  5. 寫入後對每個建議 tag 呼叫 video_repo.add_tag(video_id, tag)
  6. 回 Discord 卡片（顯示 title / topic / tags + 底部固定附「回覆小抄」），
     set_message_id 記住卡片訊息 ID
```

### ② Discord 回覆語法（增量 +/-）

對某張影片卡片**回覆**一則訊息，依「開頭字元」判斷模式：

- 若整則訊息以 `#` / `+` / `-` 開頭 → **標籤編輯模式**，以空白切 token，逐一處理：
  - `#X`  → 設主分類 topic = X（`set_topic`）
  - `-X`  → 移除標籤 X（`remove_tag`）
  - `+X`  → 新增標籤 X（`add_tag`）
  - 裸 token（接在前面之後、無前綴）→ 視為新增標籤（`+` 可省）
  - 例：`#唐朝 +經濟 戰爭 -制度` → topic=唐朝、加「經濟」「戰爭」、刪「制度」
- 否則（一般文字）→ **改標題**（rename，與食譜回覆改名同一肌肉記憶）

回覆處理後，bot 編輯/回覆卡片反映最新狀態。

### ②.5 求助 / 提示（「越笨越好」）

設計原則：**把小抄印在卡片上，使用者永遠不用記語法。**

- **每張影片卡片底部固定附「回覆小抄」**（card footer），回覆時說明就在輸入框正上方：
  ```
  ✏️ 想整理？直接「回覆」這則訊息：
  • 改主題 → 打 #主題        例：#唐朝
  • 加標籤 → 打 +標籤        例：+經濟 戰爭（空格分多個）
  • 刪標籤 → 打 -標籤        例：-制度
  • 改標題 → 直接打新標題（不用任何符號）
  可混用，例：#唐朝 +經濟 -制度
  ```
- **打 `help` / `?` / `？` / 任何看不懂的純文字** → bot 直接回同一張小抄
  （把第 5 段「純文字 → 提示」這條做成「發小抄」，而非冷冰冰錯誤訊息）。
- 小抄文字抽成 `video/ingest.py` 或 handler 的一個常數（`_CHEAT_SHEET`），卡片 footer 與 help 回覆共用同一份，避免兩處走鐘。

### ③ 網頁 PWA（主力編輯器）

見第 4 段前端規格的底部 sheet。

## 3. API 路由（routes/videos.py，全部 `Depends(require_token)`）

```
GET    /api/videos
        → {videos: [{id, title, url, topic, channel, platform,
                     thumbnail, tags: [..], created_at}]}
        回全部、前端再過濾（與 food 一致，先不做 server 端 query 參數，YAGNI）。
        thumbnail：YouTube 由 url 解出 id 算出縮圖網址；非 YouTube 為 null。

PUT    /api/videos/{id}              body {title?, topic?}   → {video: {...}}
POST   /api/videos/{id}/tags         body {tag}              → {video: {...}}（含更新後 tags）
DELETE /api/videos/{id}/tags/{tag}                            → {ok: true}
        （tag 走 path param，前端 encodeURIComponent 處理中文/特殊字）
DELETE /api/videos/{id}                                       → {ok: true}（CASCADE 刪 tags）
```

在 `main.py` 第 16 行附近 `from routes.videos import router as videos_router` 並 `include_router`，
**務必在第 28 行 `create_all` 之前 import**（讓新 model 註冊到 Base.metadata）。

### video/repo.py 函式（沿用食譜/食記命名慣例）

```python
def to_dict(rec) -> dict                       # 含 thumbnail（由 url 算）
def add_video(title, url, topic=None, channel=None, platform=None) -> tuple[dict, bool]  # upsert by url
def list_videos(topic=None) -> list[dict]      # 每筆附 tags
def rename(video_id, title) -> dict | None
def set_topic(video_id, topic) -> dict | None
def add_tag(video_id, tag) -> bool             # 冪等：已存在則略過
def remove_tag(video_id, tag) -> bool
def tags_for(video_id) -> list[str]
def tags_by_video() -> dict[int, list[str]]    # 給 list_videos 一次附掛（仿 photos_by_place）
def set_message_id(video_id, message_id) -> None
def get_by_message_id(message_id) -> dict | None
def delete_video(video_id) -> bool
```

## 4. 前端（手機 PWA）

### App.jsx
`TABS` 加 `{ key: 'video', icon: '🎥', label: '歷史' }`，並 `{tab === 'video' && <Videos />}`。

### frontend/src/Videos.jsx
- **頂部**：一排「書架」chips（由 `DISTINCT topic` 動態長出 + 一個「全部」）＋ 搜尋框
  （同時比對 title 與 tags）。點書架 = 按分類瀏覽；打字 = 標籤/關鍵字搜尋。
- **清單卡片**：縮圖（YouTube thumbnail，否則 emoji 墊底）＋ title ＋ channel ＋ topic 徽章 ＋ tag chips。
- **點卡片 → 底部 sheet**（沿用 PlaceSheet 結構）：
  - topic 下拉/可編輯
  - tag chips：每個帶 ✕（呼叫 removeVideoTag）
  - 加標籤輸入框：自動補既有標籤（前端用 DISTINCT tag 當建議清單）
  - 「▶️ 開啟」跳原片（target=_blank）
  - 改名、刪除

### frontend/src/api.js（沿用 authedFetch）
```js
getVideos()                       // GET /api/videos
updateVideo(id, {title, topic})   // PUT /api/videos/{id}
addVideoTag(id, tag)              // POST /api/videos/{id}/tags
removeVideoTag(id, tag)           // DELETE /api/videos/{id}/tags/{encodeURIComponent(tag)}
deleteVideo(id)                   // DELETE /api/videos/{id}
```

### frontend/src/index.css
補影片清單/卡片/書架 chips/sheet 編輯器樣式（沿用既有設計 token，如 `--brand`）。

## 5. 接線（照食記/食譜 7 步骨架）

1. `.env`：`HISTORY_VIDEO_INGEST_CHANNEL_ID`（已新增，第 30 行）。
2. `discordbot/bot.py` `on_message`：加 `video_chan = os.getenv("HISTORY_VIDEO_INGEST_CHANNEL_ID")`，
   `if video_chan and ch_id == video_chan: await ingest_handlers.handle_video_message(message); return`。
3. `discordbot/ingest_handlers.py`：新增 `handle_video_message`
   （回覆 → 編輯；連結 → 攝取；`help`/`?`/純文字 → 發 `_CHEAT_SHEET` 小抄）。
4. `video/` 新模組：`extract.py`（yt-dlp 抓取 + `_VIDEO_PROMPT` LLM 吐 topic+tags + `youtube_id()`/`youtube_thumbnail()`/`parse json`）、
   `ingest.py`（orchestrator）、`repo.py`（上方函式）、`__init__.py`。
5. `models.py`：兩張新表。
6. `routes/videos.py` + `main.py` 註冊（create_all 之前 import）。
7. 前端：App.jsx / Videos.jsx / api.js / index.css。

## 6. 不做（YAGNI / 明確排除）

- 影片檔上傳/下載/轉檔（純連結收集）。
- 已看/未看、進度追蹤。
- 拉霸隨機抽。
- 正規化標籤表（tags 表 + 關聯表）。
- server 端 query 過濾參數（先回全部、client 過濾）。

## 7. 文件（專案鐵律：同一 commit 必更新）

- `README.md`：新增 🎥 歷史影片模組說明、新環境變數。
- `CODEBASE.md`：新模組 `video/`、兩張新表、5 條 API、新頻道變數。

## 8. 實作期要驗證的點（writing-plans / TDD 時確認）

- yt-dlp 對目標連結（YouTube 為主）能取到 title/uploader/description；B 站等退回 og:meta。
- `_VIDEO_PROMPT` 實測能穩定吐合法 JSON `{topic, tags:[]}`（沿用 `parse_extracted_json` 容錯）。
- `youtube_id()` 能解析 `watch?v=`、`youtu.be/`、`shorts/` 三種型態。
- Discord 回覆語法解析：`#`/`+`/`-` 開頭進標籤模式，其餘為改名；中文標籤含空白的處理。
- DELETE tag 的中文 path param 在 ngrok + FastAPI 下正確解碼。
