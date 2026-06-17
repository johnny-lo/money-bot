# 歷史教學影片模組 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增第四個頻道模組 🎥 歷史教學影片——專屬 Discord 頻道丟連結 → AI 判主題+標籤 → Discord 增量微調 / 手機 PWA 主力編輯，之後按分類瀏覽或標籤搜尋找回影片。

**Architecture:** 沿用「食譜」連結收集骨架（classify_platform + food.extract.from_url 的 yt-dlp 抓取）。資料層 = `history_videos`（主分類 topic 單一書架）+ `video_tags`（去正規化多對多，標籤直接存字串）。三層編輯共用同一組 `video/repo.py` 函式：① AI 首判 ② Discord 回覆增量 `#topic +tag -tag` ③ PWA 視覺化 sheet。每張卡片附「越笨越好」回覆小抄。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy（Postgres）/ discord.py / yt-dlp / codex_cli / React 18 + Vite 5。

**Spec:** [docs/superpowers/specs/2026-06-17-history-video-module-design.md](../specs/2026-06-17-history-video-module-design.md)

**分支：** 沿用現有 `feat/mobile-pwa-frontend`（整個 PWA 工作都在這支，不另開）。

**測試怎麼跑：** 本專案測試是純單元（introspection / FakeSession，不連真 DB）。指令一律
`python -m pytest <檔> -v`。若 host 沒裝依賴，改用 `docker exec money-bot python -m pytest <檔> -v`
（container live-mount `.:/app`，看得到新檔）。本 plan 一律寫 host 版指令。

**部署節奏：** 後端改 → `docker restart money-bot`（重啟會跑開機發票同步，~30–90s 才 ready，期間 curl 回 000 是正常不是壞）；前端改 → `npm run build --prefix frontend`（live-mount 直接生效，使用者硬重整）。

---

## File Structure

新增：
- `video/__init__.py` — 空（讓 `video` 成 package）
- `video/extract.py` — 純抽取：`_VIDEO_PROMPT`、`parse_video_meta`（LLM JSON → {topic,tags}）、`meta_from_text`（codex）、`youtube_thumbnail`（reuse food.extract.parse_video_id）
- `video/commands.py` — 純 UX 邏輯：`parse_reply_command`（Discord 回覆語法）、`CHEAT_SHEET`（小抄文字，單一真相）
- `video/ingest.py` — orchestrator：`from_url(url, caption)`（連結 → 入庫 + 掛標籤）
- `video/repo.py` — DB 存取：影片 CRUD + 標籤 CRUD
- `routes/videos.py` — 5 條 JSON API
- `frontend/src/Videos.jsx` — 🎥 分頁
- `tests/test_video_model.py`、`tests/test_video_extract.py`、`tests/test_video_commands.py`、`tests/test_video_repo.py`

修改：
- `models.py` — 加 `HistoryVideo` + `VideoTag`
- `discordbot/embeds.py` — 加 `COLOR_VIDEO`、`video_card_embed`、`video_help_embed`、`video_missing_embed`
- `discordbot/ingest_handlers.py` — 加 `handle_video_message`
- `discordbot/bot.py` — `on_message` 加頻道分流
- `main.py` — import + `include_router(videos_router)`
- `frontend/src/App.jsx` — 加 🎥 分頁
- `frontend/src/api.js` — 加 video 相關函式
- `frontend/src/index.css` — 補影片分頁樣式
- `README.md`、`CODEBASE.md` — 文件（最後一個 commit）

---

## Task 1: 資料模型（兩張表）

**Files:**
- Modify: `models.py`（檔尾，緊接 `FoodPhoto` 之後）
- Test: `tests/test_video_model.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_video_model.py`：
```python
from models import HistoryVideo, VideoTag


def test_history_video_table_and_columns():
    assert HistoryVideo.__tablename__ == "history_videos"
    cols = {c.name for c in HistoryVideo.__table__.columns}
    assert cols == {
        "id", "title", "url", "topic", "channel",
        "platform", "discord_message_id", "created_at",
    }


def test_history_video_url_unique_and_indexed():
    assert HistoryVideo.__table__.columns["url"].unique is True
    assert HistoryVideo.__table__.columns["url"].index is True
    assert HistoryVideo.__table__.columns["topic"].index is True
    assert HistoryVideo.__table__.columns["discord_message_id"].index is True


def test_video_tag_table_and_columns():
    assert VideoTag.__tablename__ == "video_tags"
    cols = {c.name for c in VideoTag.__table__.columns}
    assert cols == {"id", "video_id", "tag"}


def test_video_tag_fk_cascade():
    fks = list(VideoTag.__table__.columns["video_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "history_videos"
    assert fks[0].ondelete == "CASCADE"
    assert VideoTag.__table__.columns["video_id"].index is True
    assert VideoTag.__table__.columns["tag"].index is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_video_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'HistoryVideo' from 'models'`

- [ ] **Step 3: 加 model**

`models.py` 檔尾加（`func`、`ForeignKey` 已在第 1 行 import）：
```python


class HistoryVideo(Base):
    """歷史教學影片：一支影片 + 一個連結。topic=主分類書架（一支一個）。"""
    __tablename__ = "history_videos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)                      # yt-dlp 標題，LLM 清乾淨；可被 reply 改名
    url = Column(String, unique=True, index=True)           # 原始連結（去重鍵）
    topic = Column(String, nullable=True, index=True)       # 主分類/書架
    channel = Column(String, nullable=True)                 # 講師/頻道名（yt-dlp uploader）
    platform = Column(String, nullable=True)                # youtube / other …
    discord_message_id = Column(String, nullable=True, index=True)  # 卡片訊息 ID（reply 編輯回查）
    created_at = Column(DateTime, default=func.now())


class VideoTag(Base):
    """影片標籤（去正規化多對多）：一支影片多個標籤，標籤直接存字串。"""
    __tablename__ = "video_tags"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("history_videos.id", ondelete="CASCADE"),
                      index=True, nullable=False)            # 刪影片時 DB 列自動清
    tag = Column(String, index=True, nullable=False)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_video_model.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_video_model.py
git commit -m "feat(video): history_videos + video_tags 兩張表（主分類+去正規化標籤）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 純抽取 helper（LLM 主題+標籤 / 縮圖）

**Files:**
- Create: `video/__init__.py`（空檔）
- Create: `video/extract.py`
- Test: `tests/test_video_extract.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_video_extract.py`：
```python
from video.extract import parse_video_meta, youtube_thumbnail


def test_parse_clean_json():
    out = parse_video_meta('{"topic":"唐朝","tags":["經濟","戰爭","制度"]}')
    assert out == {"topic": "唐朝", "tags": ["經濟", "戰爭", "制度"]}


def test_parse_strips_markdown_fence():
    out = parse_video_meta('```json\n{"topic":"明清","tags":["科舉"]}\n```')
    assert out == {"topic": "明清", "tags": ["科舉"]}


def test_parse_dedupes_and_caps_five_tags():
    out = parse_video_meta('{"topic":"x","tags":["a","a","b","c","d","e","f"]}')
    assert out["tags"] == ["a", "b", "c", "d", "e"]   # 去重後截 5


def test_parse_bad_json_returns_empty():
    assert parse_video_meta("看不懂") == {"topic": "", "tags": []}
    assert parse_video_meta('{"topic":123}') == {"topic": "", "tags": []}  # tags 缺 → []


def test_parse_non_dict_returns_empty():
    assert parse_video_meta('["a","b"]') == {"topic": "", "tags": []}


def test_youtube_thumbnail():
    assert youtube_thumbnail("https://youtu.be/dQw4w9WgXcQ") == \
        "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert youtube_thumbnail("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == \
        "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_youtube_thumbnail_non_youtube_is_none():
    assert youtube_thumbnail("https://www.bilibili.com/video/BV1xx") is None
    assert youtube_thumbnail("") is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_video_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'video'`

- [ ] **Step 3: 建 package + 實作**

`video/__init__.py`：空檔（`touch video/__init__.py`）。

`video/extract.py`：
```python
"""連結文字 blob → {topic, tags}（codex），以及 YouTube 縮圖。

- parse_video_meta：純函式，把 codex 回應字串解析成 {topic, tags}（壞 JSON/缺欄位回空）
- meta_from_text：用 codex_text 從一段文字判主題+標籤
- youtube_thumbnail：reuse food.extract.parse_video_id → 縮圖網址（非 YouTube 回 None）
"""
import json

from codex_cli import codex_text
from food.extract import parse_video_id


_VIDEO_PROMPT = (
    "以下是一支歷史教學影片的標題與描述。請判斷它的「主題」與「標籤」。\n"
    "規則：\n"
    "- topic：給單一最貼切的主題分類（例：唐朝、明清、世界大戰、台灣史），這是書架，一支只放一格；判斷不出回空字串。\n"
    "- tags：給 3~5 個跨主題的關鍵字標籤（例：經濟、戰爭、制度、人物），用繁體中文、不重複；判斷不出回空陣列。\n"
    "只回 JSON、不要 markdown 標籤：\n"
    '{{"topic":"主題(判斷不出就空字串)","tags":["標籤1","標籤2"]}}\n\n'
    "內容：\n{text}"
)

_MAX_TAGS = 5


def _strip_fence(t: str) -> str:
    t = (t or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def parse_video_meta(raw: str) -> dict:
    """codex 回應 → {topic:str, tags:[str]}。壞 JSON / 非 dict / 缺欄位皆安全降級。"""
    try:
        d = json.loads(_strip_fence(raw))
    except (ValueError, TypeError):
        return {"topic": "", "tags": []}
    if not isinstance(d, dict):
        return {"topic": "", "tags": []}
    topic = d.get("topic")
    topic = topic.strip() if isinstance(topic, str) else ""
    tags: list[str] = []
    raw_tags = d.get("tags")
    if isinstance(raw_tags, list):
        for x in raw_tags:
            s = x.strip() if isinstance(x, str) else ""
            if s and s not in tags:
                tags.append(s)
    return {"topic": topic, "tags": tags[:_MAX_TAGS]}


def meta_from_text(text: str) -> dict:
    """一段文字 → {topic, tags}（codex）。抽不到回空。"""
    return parse_video_meta(codex_text(_VIDEO_PROMPT.format(text=text)))


def youtube_thumbnail(url: str) -> str | None:
    """YouTube URL → hqdefault 縮圖網址；非 YouTube / 解不出回 None。"""
    vid = parse_video_id(url)
    return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if vid else None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_video_extract.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add video/__init__.py video/extract.py tests/test_video_extract.py
git commit -m "feat(video): 純抽取 helper——LLM 判主題+標籤、YouTube 縮圖

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Discord 回覆語法 parser + 小抄常數

**Files:**
- Create: `video/commands.py`
- Test: `tests/test_video_commands.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_video_commands.py`：
```python
from video.commands import parse_reply_command, CHEAT_SHEET


def test_rename_when_no_marker():
    assert parse_reply_command("唐朝的經濟與賦稅") == {
        "mode": "rename", "title": "唐朝的經濟與賦稅",
    }


def test_empty_is_noop():
    assert parse_reply_command("   ") == {"mode": "noop"}
    assert parse_reply_command("") == {"mode": "noop"}


def test_set_topic_only():
    out = parse_reply_command("#唐朝")
    assert out == {"mode": "edit", "topic": "唐朝", "add": [], "remove": []}


def test_add_with_plus_and_bare_tokens():
    # + 之後的裸 token 也算新增
    out = parse_reply_command("+經濟 戰爭")
    assert out == {"mode": "edit", "topic": None, "add": ["經濟", "戰爭"], "remove": []}


def test_remove():
    out = parse_reply_command("-制度")
    assert out == {"mode": "edit", "topic": None, "add": [], "remove": ["制度"]}


def test_mixed_all_ops():
    out = parse_reply_command("#唐朝 +經濟 戰爭 -制度")
    assert out == {
        "mode": "edit", "topic": "唐朝",
        "add": ["經濟", "戰爭"], "remove": ["制度"],
    }


def test_marker_only_no_payload_is_edit_with_nothing():
    # 只打一個 "+"（無內容）→ edit 但什麼也沒帶（handler 視為 noop）
    out = parse_reply_command("+")
    assert out == {"mode": "edit", "topic": None, "add": [], "remove": []}


def test_cheat_sheet_mentions_all_four_ops():
    for marker in ("#", "+", "-"):
        assert marker in CHEAT_SHEET
    assert "改標題" in CHEAT_SHEET
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_video_commands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'video.commands'`

- [ ] **Step 3: 實作**

`video/commands.py`：
```python
"""Discord 回覆語法解析（純函式）+ 回覆小抄文字（單一真相）。

語法（對影片卡片 reply）：
- 整串以 # / + / - 開頭 → 標籤編輯模式，空白切 token：
    #X 設主題、+X 加標籤、-X 刪標籤、裸 token 視為加標籤
- 否則 → 改標題（rename）
- 空字串 → noop
"""

CHEAT_SHEET = (
    "✏️ 想整理？直接「回覆」這則訊息：\n"
    "• 改主題 → 打 #主題        例：#唐朝\n"
    "• 加標籤 → 打 +標籤        例：+經濟 戰爭（空格分多個）\n"
    "• 刪標籤 → 打 -標籤        例：-制度\n"
    "• 改標題 → 直接打新標題（不用任何符號）\n"
    "可混用，例：#唐朝 +經濟 -制度"
)


def parse_reply_command(text: str) -> dict:
    """回覆文字 → 指令 dict。

    - {"mode": "noop"}
    - {"mode": "rename", "title": str}
    - {"mode": "edit", "topic": str|None, "add": [str], "remove": [str]}
    """
    t = (text or "").strip()
    if not t:
        return {"mode": "noop"}
    if t[0] not in "#+-":
        return {"mode": "rename", "title": t}

    topic = None
    add: list[str] = []
    remove: list[str] = []
    for tok in t.split():
        if tok.startswith("#"):
            name = tok[1:].strip()
            if name:
                topic = name
        elif tok.startswith("-"):
            name = tok[1:].strip()
            if name:
                remove.append(name)
        elif tok.startswith("+"):
            name = tok[1:].strip()
            if name:
                add.append(name)
        else:
            # 裸 token（接在前面之後）視為加標籤
            add.append(tok.strip())
    return {"mode": "edit", "topic": topic, "add": add, "remove": remove}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_video_commands.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add video/commands.py tests/test_video_commands.py
git commit -m "feat(video): 回覆語法 parser（#主題 +標籤 -標籤 / 改標題）+ 小抄常數

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Repo 層（影片 + 標籤 CRUD）

**Files:**
- Create: `video/repo.py`
- Test: `tests/test_video_repo.py`

> 說明：`to_dict` 是純函式（單一 ORM 物件 → dict，thumbnail 由 url 算），可不連 DB 單測。
> 其餘 DB 函式沿用 `recipe/repo.py` 的 `SessionLocal` 慣例；本任務只為 `to_dict` 寫單測，
> DB 函式由「Task 7 curl smoke + Task 6 Discord smoke」做端對端驗證（與本專案 repo 既有測試姿態一致——
> `recipe/repo.py` 也無 repo 級單測，只有 model-shape + 純函式測）。

- [ ] **Step 1: 寫失敗測試（純函式 to_dict）**

`tests/test_video_repo.py`：
```python
from models import HistoryVideo
from video.repo import to_dict


def _vid(**kw):
    v = HistoryVideo(**kw)
    if v.id is None:
        v.id = 1
    return v


def test_to_dict_youtube_has_thumbnail():
    v = _vid(title="唐朝", url="https://youtu.be/dQw4w9WgXcQ",
             topic="唐朝", channel="某頻道", platform="youtube")
    d = to_dict(v, tags=["經濟", "戰爭"])
    assert d["title"] == "唐朝"
    assert d["topic"] == "唐朝"
    assert d["tags"] == ["經濟", "戰爭"]
    assert d["thumbnail"] == "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_to_dict_non_youtube_thumbnail_none_and_default_tags():
    v = _vid(title="x", url="https://www.bilibili.com/video/BV1", platform="other")
    d = to_dict(v)
    assert d["thumbnail"] is None
    assert d["tags"] == []        # 沒帶 tags → 預設空陣列
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_video_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'to_dict' from 'video.repo'`

- [ ] **Step 3: 實作 repo**

`video/repo.py`：
```python
"""HistoryVideo + VideoTag 的 DB 存取（沿用 recipe/repo.py 的 SessionLocal 慣例）。

標籤去正規化：VideoTag 直接存標籤字串。查某標籤=WHERE tag=?；全部標籤=DISTINCT tag。
"""
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import HistoryVideo, VideoTag
from video.extract import youtube_thumbnail


def to_dict(rec: HistoryVideo, tags: list[str] | None = None) -> dict:
    """ORM → dict。thumbnail 由 url 算；tags 由呼叫端附（預設空）。"""
    return {
        "id": rec.id,
        "title": rec.title,
        "url": rec.url,
        "topic": rec.topic,
        "channel": rec.channel,
        "platform": rec.platform,
        "thumbnail": youtube_thumbnail(rec.url or ""),
        "tags": tags or [],
        "discord_message_id": rec.discord_message_id,
        "created_at": rec.created_at.isoformat() if rec.created_at else "",
    }


def _get_by_url(db, url: str):
    return db.query(HistoryVideo).filter(HistoryVideo.url == url).first()


def tags_for(video_id: int) -> list[str]:
    """某影片的標籤（建立順序）。"""
    db = SessionLocal()
    try:
        rows = (db.query(VideoTag)
                .filter(VideoTag.video_id == video_id)
                .order_by(VideoTag.id.asc()).all())
        return [r.tag for r in rows]
    finally:
        db.close()


def tags_by_video() -> dict[int, list[str]]:
    """一次撈全部標籤，分組成 {video_id: [tag]}（給 list_videos 附掛，仿 photos_by_place）。"""
    db = SessionLocal()
    try:
        rows = db.query(VideoTag).order_by(VideoTag.id.asc()).all()
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(r.video_id, []).append(r.tag)
        return out
    finally:
        db.close()


def add_video(title: str, url: str, topic: str | None = None,
              channel: str | None = None, platform: str | None = None) -> tuple[dict, bool]:
    """以 url 去重。回 (dict, created)。併發撞 UNIQUE(url) → rollback → 當『已收錄』回。"""
    db = SessionLocal()
    try:
        existing = _get_by_url(db, url)
        if existing is not None:
            return to_dict(existing), False
        rec = HistoryVideo(title=title, url=url, topic=topic,
                           channel=channel, platform=platform)
        db.add(rec)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            dup = _get_by_url(db, url)
            if dup is not None:
                return to_dict(dup), False
            raise
        db.refresh(rec)
        return to_dict(rec), True
    finally:
        db.close()


def list_videos(topic: str | None = None) -> list[dict]:
    """列出影片（新到舊），每筆附 tags。topic 給值則只回該書架。"""
    tags_map = tags_by_video()
    db = SessionLocal()
    try:
        q = db.query(HistoryVideo)
        if topic:
            q = q.filter(HistoryVideo.topic == topic)
        rows = q.order_by(HistoryVideo.created_at.desc()).all()
        return [to_dict(r, tags=tags_map.get(r.id, [])) for r in rows]
    finally:
        db.close()


def _get(db, video_id: int):
    return db.query(HistoryVideo).filter(HistoryVideo.id == video_id).first()


def get(video_id: int) -> dict | None:
    """單筆（含 tags）。查無回 None。"""
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return None
        out = to_dict(rec)
    finally:
        db.close()
    out["tags"] = tags_for(video_id)
    return out


def rename(video_id: int, title: str) -> dict | None:
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return None
        rec.title = (title or "").strip()
        db.commit()
    finally:
        db.close()
    return get(video_id)


def set_topic(video_id: int, topic: str) -> dict | None:
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return None
        rec.topic = (topic or "").strip() or None
        db.commit()
    finally:
        db.close()
    return get(video_id)


def add_tag(video_id: int, tag: str) -> bool:
    """加一個標籤（冪等：同 video 同 tag 已存在則略過）。video 不存在回 False。"""
    tag = (tag or "").strip()
    if not tag:
        return False
    db = SessionLocal()
    try:
        if _get(db, video_id) is None:
            return False
        dup = (db.query(VideoTag)
               .filter(VideoTag.video_id == video_id, VideoTag.tag == tag).first())
        if dup is not None:
            return True
        db.add(VideoTag(video_id=video_id, tag=tag))
        db.commit()
        return True
    finally:
        db.close()


def remove_tag(video_id: int, tag: str) -> bool:
    """刪一個標籤。True=刪了，False=查無。"""
    tag = (tag or "").strip()
    db = SessionLocal()
    try:
        row = (db.query(VideoTag)
               .filter(VideoTag.video_id == video_id, VideoTag.tag == tag).first())
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


def delete_video(video_id: int) -> bool:
    """刪影片（FK CASCADE 連帶刪 video_tags）。True=刪了，False=查無。"""
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is None:
            return False
        db.delete(rec)
        db.commit()
        return True
    finally:
        db.close()


def set_message_id(video_id: int, message_id) -> None:
    db = SessionLocal()
    try:
        rec = _get(db, video_id)
        if rec is not None:
            rec.discord_message_id = str(message_id)
            db.commit()
    finally:
        db.close()


def get_by_message_id(message_id) -> dict | None:
    """從卡片訊息 ID 反查影片（含 tags）。查無回 None。"""
    db = SessionLocal()
    try:
        rec = (db.query(HistoryVideo)
               .filter(HistoryVideo.discord_message_id == str(message_id)).first())
        vid = rec.id if rec is not None else None
    finally:
        db.close()
    return get(vid) if vid is not None else None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_video_repo.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add video/repo.py tests/test_video_repo.py
git commit -m "feat(video): repo——影片 upsert/list/rename/delete + 標籤 add/remove（去正規化）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Ingest orchestrator（連結 → 入庫 + 掛標籤）

**Files:**
- Create: `video/ingest.py`
- Test: `tests/test_video_ingest.py`

- [ ] **Step 1: 寫失敗測試（monkeypatch 掉抽取與 repo，只測編排邏輯）**

`tests/test_video_ingest.py`：
```python
import video.ingest as ing


def test_from_url_happy_path(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "唐朝的經濟\n某史頻道")
    monkeypatch.setattr(ing, "meta_from_text", lambda t: {"topic": "唐朝", "tags": ["經濟", "戰爭"]})
    monkeypatch.setattr(ing.repo, "add_video",
                        lambda title, url, topic=None, channel=None, platform=None:
                        ({"id": 7, "title": title, "topic": topic, "tags": []}, True))
    added = []
    monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: added.append((vid, tag)) or True)

    rec, reason = ing.from_url("https://youtu.be/x")
    assert reason == ""
    assert rec["id"] == 7 and rec["topic"] == "唐朝"
    assert rec["_created"] is True
    assert rec["tags"] == ["經濟", "戰爭"]      # 回傳前把建議標籤帶上，省一次查詢
    assert added == [(7, "經濟"), (7, "戰爭")]   # 標籤逐一入庫


def test_from_url_extract_fail_returns_reason(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    def boom(u, p):
        raise RuntimeError("yt-dlp 掛了")
    monkeypatch.setattr(ing, "_extract_from_url", boom)
    rec, reason = ing.from_url("https://youtu.be/x")
    assert rec is None and "yt-dlp 掛了" in reason


def test_from_url_no_title_falls_back_to_blob_first_line(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "other")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "  某個影片標題  \n第二行")
    monkeypatch.setattr(ing, "meta_from_text", lambda t: {"topic": "", "tags": []})
    captured = {}
    monkeypatch.setattr(ing.repo, "add_video",
                        lambda title, url, topic=None, channel=None, platform=None:
                        (captured.update(title=title, topic=topic) or {"id": 1, "tags": []}, True))
    monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: True)
    rec, reason = ing.from_url("https://example.com/x")
    assert reason == ""
    assert captured["title"] == "某個影片標題"   # blob 第一行當標題
    assert captured["topic"] is None             # 空 topic 不寫空字串，存 None


def test_from_url_blank_blob_returns_reason(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "other")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "")
    rec, reason = ing.from_url("https://example.com/x")
    assert rec is None and reason == ing._NO_TITLE_REASON
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_video_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'video.ingest'`

- [ ] **Step 3: 實作**

`video/ingest.py`：
```python
"""連結 → 文字 blob → {topic,tags} + 乾淨標題 → 入庫 HistoryVideo + 掛標籤。

回 (video_dict_or_None, reason)：
- 非 None → 入庫成功，含 _created（True=新增 / False=已收錄過）與 tags
- None    → reason 為提示字串（呼叫端回卡片）

最大化複用美食抽取基建：classify_platform + food.extract.from_url（yt-dlp 抓 title/uploader/desc）。
"""
from food.links import classify_platform
from food.extract import from_url as _extract_from_url
from video import repo
from video.extract import meta_from_text


_NO_TITLE_REASON = "抽不到影片標題"


def from_url(url: str, *, caption: str = "") -> tuple[dict | None, str]:
    """從連結入庫影片。caption=使用者去 URL 後的文字註解（若有，優先併入餵 AI）。"""
    platform = classify_platform(url)

    try:
        blob = _extract_from_url(url, platform)
    except Exception as ex:
        return None, f"連結抽取失敗：{ex}"

    pieces = [p for p in (caption.strip() if caption else "", blob or "") if p]
    text = "\n".join(pieces)

    meta = {"topic": "", "tags": []}
    if text:
        try:
            meta = meta_from_text(text)
        except Exception:
            meta = {"topic": "", "tags": []}   # AI 失敗不擋入庫，標題仍可退 blob 第一行

    # 標題：優先 blob 第一行（yt-dlp 第一段就是 title）；空白防 IndexError
    title = ""
    if blob:
        title = (blob.strip().splitlines() or [""])[0].strip()
    if not title:
        return None, _NO_TITLE_REASON

    topic = meta.get("topic") or None        # 空字串存 None
    rec, created = repo.add_video(title, url, topic=topic, platform=platform)
    for tag in meta.get("tags", []):
        repo.add_tag(rec["id"], tag)

    rec["_created"] = created
    rec["tags"] = meta.get("tags", [])       # 回傳前帶上建議標籤，省一次查詢
    return rec, ""
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_video_ingest.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 全套回歸 + Commit**

Run: `python -m pytest tests/ -v`（確認沒打到既有測試）
Expected: 全 PASS

```bash
git add video/ingest.py tests/test_video_ingest.py
git commit -m "feat(video): ingest orchestrator——連結抽取 → 判主題+標籤 → 入庫掛標籤

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Discord 卡片 / 小抄 embed + handler + 頻道分流

**Files:**
- Modify: `discordbot/embeds.py`（加顏色 + 3 個 builder）
- Modify: `discordbot/ingest_handlers.py`（加 `handle_video_message`）
- Modify: `discordbot/bot.py`（`on_message` 加分流）
- Test: `tests/test_video_embeds.py`

> handler 走 discord I/O，沿用 `handle_recipe_message` 結構，靠下方 Discord smoke 驗證。
> embed builder 是純呈現層，可單測「卡片含小抄、平台/編號欄位正確」。

- [ ] **Step 1: 寫失敗測試（embed builder 純呈現）**

`tests/test_video_embeds.py`：
```python
from discordbot.embeds import video_card_embed, video_help_embed
from video.commands import CHEAT_SHEET


def test_card_has_cheatsheet_and_fields():
    e = video_card_embed(
        {"id": 7, "title": "唐朝的經濟", "topic": "唐朝", "platform": "youtube",
         "url": "https://youtu.be/x", "tags": ["經濟", "戰爭"]},
        created=True,
    )
    blob = e.title + (e.footer.text or "") + " ".join(
        f"{f.name}{f.value}" for f in e.fields
    )
    assert "唐朝的經濟" in e.title
    assert "唐朝" in blob and "經濟" in blob       # topic + tags 有顯示
    assert CHEAT_SHEET in blob                      # 小抄印在卡片上


def test_help_embed_is_cheatsheet():
    e = video_help_embed()
    assert CHEAT_SHEET in (e.description or "")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_video_embeds.py -v`
Expected: FAIL — `ImportError: cannot import name 'video_card_embed'`

- [ ] **Step 3a: embeds.py**

`discordbot/embeds.py`：顏色常數區（`COLOR_RECIPE` 那行之後）加：
```python
COLOR_VIDEO   = 0x8E44AD   # 歷史影片紫
```

檔尾加 3 個 builder：
```python
def video_card_embed(v: dict, *, created: bool = True) -> discord.Embed:
    from video.commands import CHEAT_SHEET
    title = (f"🎥 已收錄：{v['title']}" if created else f"🎥 你已收錄過：{v['title']}")
    e = discord.Embed(title=title, color=COLOR_VIDEO)
    e.add_field(name="📚 主題", value=v.get("topic") or "（未分類）", inline=True)
    e.add_field(name="編號", value=f"#{v['id']}", inline=True)
    tags = v.get("tags") or []
    if tags:
        e.add_field(name="🏷️ 標籤", value="、".join(tags), inline=False)
    if v.get("url"):
        e.add_field(name="連結", value=v["url"], inline=False)
    e.add_field(name="✏️ 怎麼整理", value=CHEAT_SHEET, inline=False)
    return e


def video_help_embed() -> discord.Embed:
    from video.commands import CHEAT_SHEET
    return discord.Embed(title="🎥 歷史影片：怎麼用", description=CHEAT_SHEET, color=COLOR_VIDEO)


def video_missing_embed(reason: str) -> discord.Embed:
    e = discord.Embed(title="⚠️ 沒收進來", description=reason or "抽不到影片資訊", color=COLOR_WARN)
    e.set_footer(text="🔁 重貼連結，或 reply 這張卡片給我新標題")
    return e
```

- [ ] **Step 3b: 跑 embed 測試確認通過**

Run: `python -m pytest tests/test_video_embeds.py -v`
Expected: PASS（2 passed）

- [ ] **Step 3c: ingest_handlers.py**

`discordbot/ingest_handlers.py`：頂部 import 區的 embeds import 末尾，加
`video_card_embed, video_help_embed, video_missing_embed`；檔尾加：
```python
async def _send_video_card(channel, v: dict, *, created: bool) -> None:
    from video import repo as video_repo
    sent = await channel.send(embed=video_card_embed(v, created=created))
    video_repo.set_message_id(v["id"], sent.id)


async def handle_video_message(message: discord.Message):
    from video import ingest as video_ingest, repo as video_repo
    from video.commands import parse_reply_command

    # ── reply：編輯既有卡片（改名 / 設主題 / 加刪標籤）──
    ref = getattr(message, "reference", None)
    if ref and ref.message_id:
        existing = video_repo.get_by_message_id(ref.message_id)
        if not existing:
            await message.channel.send("這張卡片過期了，或重貼連結就好 🎥")
            return
        cmd = parse_reply_command(message.content or "")
        if cmd["mode"] == "rename":
            video_repo.rename(existing["id"], cmd["title"])
        elif cmd["mode"] == "edit":
            if cmd["topic"] is not None:
                video_repo.set_topic(existing["id"], cmd["topic"])
            for t in cmd["remove"]:
                video_repo.remove_tag(existing["id"], t)
            for t in cmd["add"]:
                video_repo.add_tag(existing["id"], t)
        else:  # noop
            await message.channel.send(embed=video_help_embed())
            return
        updated = video_repo.get(existing["id"])
        await _send_video_card(message.channel, updated, created=False)
        return

    # ── 連結 ingest（一連結一卡，多連結平行）──
    links = detect_links(message.content or "")
    if links:
        caption = strip_urls(message.content or "")
        async with message.channel.typing():
            results = await asyncio.gather(
                *[asyncio.to_thread(video_ingest.from_url, lk["url"], caption=caption)
                  for lk in links],
                return_exceptions=True,
            )
            for lk, res in zip(links, results):
                if isinstance(res, Exception):
                    v, reason = None, f"處理失敗：{res}"
                else:
                    v, reason = res
                if v:
                    await _send_video_card(message.channel, v, created=v.get("_created", True))
                else:
                    await message.channel.send(embed=video_missing_embed(reason))
        return

    # ── help / ? / 純文字 → 發小抄（越笨越好）──
    await message.channel.send(embed=video_help_embed())
```

- [ ] **Step 3d: bot.py 分流**

`discordbot/bot.py` `on_message`：在 `recipe_chan` 那段之後（約 line 48 之後）加：
```python
        video_chan = os.getenv("HISTORY_VIDEO_INGEST_CHANNEL_ID") or ""
        # ── 1.6) 歷史影片頻道：reply 編輯 / 連結 ingest / help ──
        if video_chan and ch_id == video_chan:
            await ingest_handlers.handle_video_message(message)
            return
```
（放在 `if recipe_chan and ch_id == recipe_chan:` 的 `return` 之後、`# ── 2) 圖片附件分流` 之前。）

- [ ] **Step 4: 全套回歸**

Run: `python -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: Commit + Discord smoke**

```bash
git add discordbot/embeds.py discordbot/ingest_handlers.py discordbot/bot.py tests/test_video_embeds.py
git commit -m "feat(video): Discord 卡片+小抄 embed、handle_video_message、頻道分流

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
docker restart money-bot
```
等 ~60–90s ready 後，在 #📜-歷史教學 頻道實測：
1. 丟一個 YouTube 連結 → 應回卡片（主題/標籤/小抄）。
2. 回覆該卡片 `#唐朝 +經濟 戰爭` → 應回更新後卡片。
3. 回覆 `-經濟` → 標籤少一個。
4. 頻道打 `help` → 回小抄。

- [ ] **Step 6: 驗證 ready / 看 log**

Run: `docker logs --tail 20 money-bot`
Expected: 看到 `Application startup complete` 與 `🐉 Discord Bot 已上線`。

---

## Task 7: JSON API（routes/videos.py）

**Files:**
- Create: `routes/videos.py`
- Modify: `main.py`（import + include_router）
- Test: `tests/test_videos_api.py`

> route handler 薄、靠 repo；本任務測 pydantic 驗證（標題不可空），端對端走 curl smoke。

- [ ] **Step 1: 寫失敗測試（pydantic body 驗證）**

`tests/test_videos_api.py`：
```python
import pytest
from pydantic import ValidationError
from routes.videos import UpdateBody, TagBody


def test_update_body_allows_partial():
    assert UpdateBody(title="新標題").title == "新標題"
    assert UpdateBody(topic="唐朝").topic == "唐朝"
    assert UpdateBody().title is None        # 兩個都可選


def test_update_body_blank_title_rejected():
    with pytest.raises(ValidationError):
        UpdateBody(title="   ")


def test_tag_body_blank_rejected():
    with pytest.raises(ValidationError):
        TagBody(tag="  ")
    assert TagBody(tag=" 經濟 ").tag == "經濟"   # strip
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_videos_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes.videos'`

- [ ] **Step 3a: routes/videos.py**

`routes/videos.py`：
```python
"""歷史影片 JSON API（PWA 🎥 分頁用）。

新增影片走 Discord 頻道（需連結抽取 pipeline）；這裡給 PWA 讀清單 + 編輯主題/標籤/刪除。
回全部、前端再過濾（與 /api/food/places 一致）。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth import require_token
from video import repo

router = APIRouter()


@router.get("/api/videos", dependencies=[Depends(require_token)])
def api_list_videos():
    """全部影片（新到舊，每筆附 tags + thumbnail）。"""
    return {"videos": repo.list_videos()}


class UpdateBody(BaseModel):
    title: str | None = None
    topic: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("標題不能是空白")
        return v

    @field_validator("topic")
    @classmethod
    def topic_strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class TagBody(BaseModel):
    tag: str

    @field_validator("tag")
    @classmethod
    def tag_not_blank(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("標籤不能是空白")
        return v


@router.put("/api/videos/{video_id}", dependencies=[Depends(require_token)])
def api_update_video(video_id: int, body: UpdateBody):
    """改標題 / 設主題（只送有改的欄位）。"""
    out = None
    if body.title is not None:
        out = repo.rename(video_id, body.title)
        if out is None:
            raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    if body.topic is not None:
        out = repo.set_topic(video_id, body.topic)
        if out is None:
            raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    if out is None:
        out = repo.get(video_id)
        if out is None:
            raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    return {"video": out}


@router.post("/api/videos/{video_id}/tags", dependencies=[Depends(require_token)])
def api_add_tag(video_id: int, body: TagBody):
    """加一個標籤。"""
    if not repo.add_tag(video_id, body.tag):
        raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    return {"video": repo.get(video_id)}


@router.delete("/api/videos/{video_id}/tags/{tag}", dependencies=[Depends(require_token)])
def api_remove_tag(video_id: int, tag: str):
    """刪一個標籤（tag 走 path param，前端 encodeURIComponent）。"""
    if not repo.remove_tag(video_id, tag):
        raise HTTPException(status_code=404, detail="找不到該標籤")
    return {"ok": True}


@router.delete("/api/videos/{video_id}", dependencies=[Depends(require_token)])
def api_delete_video(video_id: int):
    """刪一支影片（連帶刪標籤）。"""
    if not repo.delete_video(video_id):
        raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    return {"ok": True}
```

- [ ] **Step 3b: main.py 註冊**

`main.py`：
- import 區（`from routes.recipes import router as recipes_router` 之後）加：
  ```python
  from routes.videos import router as videos_router
  ```
- 掛載區（`app.include_router(recipes_router)` 之後）加：
  ```python
  app.include_router(videos_router)
  ```

- [ ] **Step 4: 跑測試 + 全套回歸**

Run: `python -m pytest tests/test_videos_api.py tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: Commit + curl smoke**

```bash
git add routes/videos.py main.py tests/test_videos_api.py
git commit -m "feat(video): JSON API——list/update/tag add-remove/delete + main 註冊

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
docker restart money-bot
```
等 ready 後（用既有裝置 token 或從 Discord `/美食地圖` 拿短 token 帶 ?token=）：
```bash
# 200 + {"videos":[...]}（需有效 token；無 token 應 401）
curl -s -H "ngrok-skip-browser-warning: true" \
  "http://127.0.0.1:8000/api/videos?token=<短token>" | head -c 400
```
Expected: JSON `{"videos": [...]}`（先前 Discord 丟過的影片應在內，含 thumbnail/tags）。

---

## Task 8: 前端 🎥 分頁

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/api.js`
- Create: `frontend/src/Videos.jsx`
- Modify: `frontend/src/index.css`

> 前端無單元測試框架，驗證走 `npm run build` + 手機實測（沿用本專案前端慣例）。

- [ ] **Step 1: api.js 加函式**

`frontend/src/api.js` 檔尾加：
```javascript

// ── 歷史影片 ─────────────────────────────────────────────────

export async function getVideos() {
  return authedFetch('/api/videos')
}

export async function updateVideo(id, payload) {
  return authedFetch(`/api/videos/${id}`, { method: 'PUT', json: payload })
}

export async function addVideoTag(id, tag) {
  return authedFetch(`/api/videos/${id}/tags`, { method: 'POST', json: { tag } })
}

export async function removeVideoTag(id, tag) {
  return authedFetch(`/api/videos/${id}/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' })
}

export async function deleteVideo(id) {
  return authedFetch(`/api/videos/${id}`, { method: 'DELETE' })
}
```

- [ ] **Step 2: App.jsx 加分頁**

`frontend/src/App.jsx`：
- import 區加 `import Videos from './Videos.jsx'`
- `TABS` 加一格：
  ```javascript
  { key: 'video', icon: '🎥', label: '歷史' },
  ```
- `<main>` 內加：
  ```javascript
  {tab === 'video' && <Videos />}
  ```

- [ ] **Step 3: Videos.jsx**

`frontend/src/Videos.jsx`：
```javascript
import { useEffect, useMemo, useState } from 'react'
import { getVideos, updateVideo, addVideoTag, removeVideoTag, deleteVideo } from './api'

// 🎥 歷史教學影片：按主題書架瀏覽 + 標籤/關鍵字搜尋。點卡片 → sheet 編輯主題/標籤。
export default function Videos() {
  const [videos, setVideos] = useState([])
  const [error, setError] = useState('')
  const [topic, setTopic] = useState('全部')   // 選中的書架
  const [q, setQ] = useState('')               // 搜尋字
  const [editing, setEditing] = useState(null) // 點某支 → 編輯 sheet
  const [newTag, setNewTag] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try { setVideos((await getVideos()).videos || []) }
    catch (e) { setError(String(e.message || e)) }
  }
  useEffect(() => { load() }, [])

  // 書架 = 所有出現過的 topic（去重）；標籤建議 = 所有出現過的 tag（去重）
  const topics = useMemo(() => {
    const s = [...new Set(videos.map((v) => v.topic).filter(Boolean))]
    return ['全部', ...s]
  }, [videos])
  const allTags = useMemo(
    () => [...new Set(videos.flatMap((v) => v.tags || []))], [videos])

  // 過濾：先套書架，再套搜尋（比對標題 + 標籤）
  const shown = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return videos.filter((v) => {
      if (topic !== '全部' && v.topic !== topic) return false
      if (!kw) return true
      const hay = (v.title + ' ' + (v.tags || []).join(' ')).toLowerCase()
      return hay.includes(kw)
    })
  }, [videos, topic, q])

  async function run(action) {
    setBusy(true)
    try { await action(); await load() }
    catch (e) { setError(String(e.message || e)) }
    finally { setBusy(false) }
  }

  // sheet 內操作後，重新從最新 videos 取這支以刷新 chips
  const fresh = editing ? videos.find((v) => v.id === editing.id) || editing : null

  return (
    <div className="video">
      {error && <div className="food-error">{error}</div>}

      {/* 書架 chips + 搜尋 */}
      <div className="video-bar">
        <div className="chips">
          {topics.map((t) => (
            <button key={t} className={t === topic ? 'chip active' : 'chip'}
                    onClick={() => setTopic(t)}>{t}</button>
          ))}
        </div>
        <input className="video-search" placeholder="🔍 搜尋標題或標籤"
               value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {/* 清單 */}
      <div className="video-list">
        <div className="recipe-count">{shown.length} 支影片</div>
        {shown.map((v) => (
          <button key={v.id} className="video-card" onClick={() => { setEditing(v); setNewTag('') }}>
            <div className="video-thumb">
              {v.thumbnail
                ? <img src={v.thumbnail} alt="" loading="lazy" />
                : '🎥'}
            </div>
            <div className="video-info">
              <div className="video-title">{v.title}</div>
              <div className="video-sub">
                {v.topic && <span className="tag visited">{v.topic}</span>}
                {v.channel && <span> {v.channel}</span>}
              </div>
              {(v.tags || []).length > 0 && (
                <div className="video-tags">{v.tags.map((t) => <span key={t} className="mini-tag">{t}</span>)}</div>
              )}
            </div>
          </button>
        ))}
      </div>

      {/* 編輯 sheet */}
      <div className={editing ? 'sheet open' : 'sheet'} onClick={() => setEditing(null)}>
        <div className="sheet-card" onClick={(e) => e.stopPropagation()}>
          <div className="sheet-handle" />
          {fresh && (
            <>
              <h3>🎥 {fresh.title}</h3>

              {/* 主題（自由字串，建議清單來自既有 topics） */}
              <label className="video-field">主題
                <input className="note-input" defaultValue={fresh.topic || ''} list="topic-list"
                       onBlur={(e) => {
                         const t = e.target.value.trim()
                         if (t !== (fresh.topic || '')) run(() => updateVideo(fresh.id, { topic: t }))
                       }} />
              </label>
              <datalist id="topic-list">
                {topics.filter((t) => t !== '全部').map((t) => <option key={t} value={t} />)}
              </datalist>

              {/* 標籤 chips：點 ✕ 刪 */}
              <div className="sheet-tags">
                {(fresh.tags || []).map((t) => (
                  <span key={t} className="mini-tag removable" onClick={() =>
                    !busy && run(() => removeVideoTag(fresh.id, t))}>{t} ✕</span>
                ))}
              </div>

              {/* 加標籤（建議清單來自所有既有標籤） */}
              <div className="tag-add">
                <input className="note-input" placeholder="加標籤" list="tag-list"
                       value={newTag} onChange={(e) => setNewTag(e.target.value)} />
                <datalist id="tag-list">
                  {allTags.map((t) => <option key={t} value={t} />)}
                </datalist>
                <button className="btn" disabled={busy || !newTag.trim()} onClick={() =>
                  run(async () => { await addVideoTag(fresh.id, newTag.trim()); setNewTag('') })}>＋</button>
              </div>

              <div className="sheet-actions">
                <a className="btn primary" href={fresh.url} target="_blank" rel="noopener">▶️ 開啟</a>
                <button className="btn danger" disabled={busy} onClick={() => {
                  if (window.confirm(`刪掉「${fresh.title}」？`))
                    run(async () => { await deleteVideo(fresh.id); setEditing(null) })
                }}>🗑️ 刪除</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: index.css 補樣式**

`frontend/src/index.css` 檔尾加（沿用既有 `--brand`、`.chip`、`.sheet`、`.note-input`、`.btn`、`.tag.visited`）：
```css
/* 🎥 歷史影片分頁 */
.video { display: flex; flex-direction: column; height: 100%; }
.video-bar { padding: calc(8px + env(safe-area-inset-top)) 12px 8px; display: flex; flex-direction: column; gap: 8px; }
.video-search { border: 1px solid #ddd; border-radius: 10px; padding: 8px 12px; font-size: 15px; }
.video-list { flex: 1; overflow-y: auto; padding: 4px 12px 16px; display: flex; flex-direction: column; gap: 10px; }
.video-card { display: flex; gap: 10px; align-items: flex-start; text-align: left;
  background: #fff; border: 1px solid #eee; border-radius: 14px; padding: 8px; width: 100%; }
.video-thumb { width: 112px; height: 63px; flex-shrink: 0; border-radius: 8px; overflow: hidden;
  background: #f3f3f3; display: flex; align-items: center; justify-content: center; font-size: 26px; }
.video-thumb img { width: 100%; height: 100%; object-fit: cover; }
.video-info { min-width: 0; flex: 1; }
.video-title { font-weight: 600; font-size: 14px; line-height: 1.3;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.video-sub { font-size: 12px; color: #888; margin-top: 2px; }
.video-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.mini-tag { font-size: 11px; background: #f0e8f5; color: #8E44AD; border-radius: 6px; padding: 1px 6px; }
.mini-tag.removable { cursor: pointer; }
.video-field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: #666; margin: 8px 0; }
.sheet-tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.tag-add { display: flex; gap: 6px; align-items: center; }
.tag-add .note-input { flex: 1; }
```

- [ ] **Step 5: Build + 手機實測**

Run: `npm run build --prefix frontend`
Expected: build 成功，`frontend/dist` 更新（live-mount 直接生效）。

手機硬重整 PWA → 點 🎥 分頁：
1. 看到 Discord 丟過的影片（YouTube 有縮圖）。
2. 點書架 chip / 打搜尋字 → 清單過濾。
3. 點卡片 → 改主題、加/刪標籤、開連結、刪除都可用。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.jsx frontend/src/api.js frontend/src/Videos.jsx frontend/src/index.css
git commit -m "feat(video): PWA 🎥 分頁——書架瀏覽+標籤搜尋+主題/標籤編輯 sheet

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 文件（專案鐵律：補 README + CODEBASE）

**Files:**
- Modify: `README.md`
- Modify: `CODEBASE.md`

- [ ] **Step 1: 讀現況**

Run: `sed -n '1,60p' README.md && echo '=====' && sed -n '1,80p' CODEBASE.md`
（找到既有「食譜模組」「頻道」「API」「資料表」段落，照同樣格式插入影片模組。）

- [ ] **Step 2: README.md**

在功能/模組清單補一段（比照食譜模組的寫法）：
- 🎥 歷史教學影片：在 `#📜-歷史教學` 頻道丟連結 → AI 判主題+標籤 → Discord 回覆 `#主題 +標籤 -標籤` 微調 / PWA 🎥 分頁編輯。
- 新環境變數：`HISTORY_VIDEO_INGEST_CHANNEL_ID`。

- [ ] **Step 3: CODEBASE.md**

補：
- 模組 `video/`：`extract.py`（LLM 判主題+標籤、YouTube 縮圖）、`commands.py`（回覆語法+小抄）、`ingest.py`（orchestrator）、`repo.py`（影片+標籤 CRUD）。
- 資料表：`history_videos`（topic 主分類）、`video_tags`（去正規化多對多）。
- API：`GET /api/videos`、`PUT /api/videos/{id}`、`POST /api/videos/{id}/tags`、`DELETE /api/videos/{id}/tags/{tag}`、`DELETE /api/videos/{id}`。
- 前端：`frontend/src/Videos.jsx` 🎥 分頁。
- 環境變數：`HISTORY_VIDEO_INGEST_CHANNEL_ID`。

- [ ] **Step 4: Commit**

```bash
git add README.md CODEBASE.md
git commit -m "docs: 歷史教學影片模組——README + CODEBASE

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 收尾驗證（全部任務完成後）

- [ ] `python -m pytest tests/ -v` 全 PASS（含新增的 video 測試檔）。
- [ ] `docker logs --tail 30 money-bot` 無 import 崩潰、`Application startup complete`、Bot 上線。
- [ ] Discord #📜-歷史教學：丟連結→卡片、回覆編輯、`help`→小抄，四項都通。
- [ ] PWA 🎥 分頁：縮圖、書架、搜尋、編輯 sheet 都通。
- [ ] `git log --oneline -9` 看到 9 個小步 commit。

## 不做（YAGNI）

已看/未看進度、拉霸隨機抽、正規化標籤表、影片檔上傳、server 端 query 過濾、bilibili 專屬縮圖（退 emoji）。

**`channel` 欄位 v1 不自動填**：`history_videos.channel` 欄位保留（nullable，前端有值才顯示），
但 ingest **不自動帶入**。原因：本模組複用 `food.extract.from_url`，它把 title/uploader/description
壓成單一 blob 餵 AI，結構化的 uploader 已經消失；要正確填 channel 得另開一次結構化 yt-dlp 抽取
（多一次網路呼叫）或重構 food 共用碼——為一個裝飾欄位不值得。日後想填，再加 `video/extract.py`
的 `yt_meta(url)` 結構化抽取即可（獨立、低風險）。
