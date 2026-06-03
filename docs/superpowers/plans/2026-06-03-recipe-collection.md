# 食譜收錄模組 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓使用者把食譜連結丟到 Discord `#🍳-食譜` 頻道自動抽出乾淨菜名存庫，之後用 `/隨機食譜` 抽一道照做，全程不動既有記帳/美食邏輯。

**Architecture:** 新增 `recipe/` 套件（`extract` 純後處理 + `repo` DB 存取 + `ingest` orchestrator）與 `Recipe` ORM；最大化複用美食模組的 `food.links`（連結偵測/分類）、`food.extract.from_url`（連結→文字 blob）、`food.pending`（補件暫存）。`discord_handler.py` 新增一個 `RECIPE_INGEST_CHANNEL_ID` 頻道分支（緊接 food 分支後、圖片分流前）、一個 `_handle_recipe_message`、3 個 slash 指令與 4 個 embed builder。

**Tech Stack:** Python 3.11、SQLAlchemy（PostgreSQL）、`codex_cli.codex_text`（ChatGPT 訂閱純文字）、discord.py、pytest。

> 對應 spec：`docs/superpowers/specs/2026-06-02-recipe-collection-design.md`
> 專案慣例：每次 commit 同步更新 `README.md` / `CODEBASE.md`（見 Task 8）。
> 測試執行：`docker compose exec -T app pytest tests/<檔> -v`
> 套用 .py 變更：`docker compose restart app`（bind mount，重啟即重新 import）

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `models.py` | 修改 | 新增 `Recipe` ORM（`url` UNIQUE 去重鍵 + `discord_message_id`） |
| `recipe/__init__.py` | 建立 | 空，標記套件 |
| `recipe/extract.py` | 建立 | blob/文字 → 乾淨菜名：`parse_name_json()`（純函式）、`name_from_text()`（codex） |
| `recipe/repo.py` | 建立 | `Recipe` DB 存取：`add_recipe`(url 去重+IntegrityError 防護)/`list_recipes`/`pick_random`/`delete_recipe`/`set_message_id`/`rename`/`get_by_message_id` |
| `recipe/ingest.py` | 建立 | 串接 `food.links`→`food.extract.from_url`→菜名→存 `Recipe`：`from_url()`（gmaps 略過 + None-blob guard） |
| `discord_handler.py` | 修改 | `COLOR_RECIPE`、4 個 `recipe_*_embed()`、`RECIPE_INGEST_CHANNEL_ID` 頻道分支、`_handle_recipe_message`、3 個 slash 指令 |
| `docker-compose.yml` | 修改 | app service 環境變數加 `RECIPE_INGEST_CHANNEL_ID` |
| `.env` | 修改 | 新增 `RECIPE_INGEST_CHANNEL_ID` |
| `README.md` / `CODEBASE.md` | 修改 | 文件同步 |
| `tests/test_recipe_extract.py` | 建立 | `parse_name_json` / `name_from_text` 後處理單元測試 |
| `tests/test_recipe_ingest.py` | 建立 | `from_url` 的 gmaps 略過 / None-blob guard / 退用 blob 第一行（mock 邊界） |
| `tests/test_recipe_repo.py` | 建立 | `pick_random` 空/非空（純函式部分；DB 不單測） |

> 不動 `routes/`、不動記帳邏輯、不動 `food/` 既有檔。

---

## Task 1: Recipe ORM

**Files:**
- Modify: `models.py`（結尾新增 class；import 已含所需型別，無需改 import）

- [ ] **Step 1: Write the failing test**

建立 `tests/test_recipe_model.py`：

```python
from models import Recipe


def test_recipe_table_and_columns():
    assert Recipe.__tablename__ == "recipes"
    cols = {c.name for c in Recipe.__table__.columns}
    assert cols == {
        "id", "name", "url", "platform", "discord_message_id", "created_at"
    }


def test_recipe_url_is_unique():
    assert Recipe.__table__.columns["url"].unique is True


def test_recipe_url_indexed():
    assert Recipe.__table__.columns["url"].index is True
    assert Recipe.__table__.columns["discord_message_id"].index is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T app pytest tests/test_recipe_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'Recipe' from 'models'`）

- [ ] **Step 3: Write minimal implementation**

在 `models.py` 結尾（`FoodPlace` class 之後）新增。`models.py` 第 1 行已 `from sqlalchemy import Column, Integer, String, DateTime, Float, func`，型別齊全：

```python


class Recipe(Base):
    """食譜收錄：一道菜 + 一個連結"""
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)                       # 乾淨菜名（codex 清理後；可被 reply 改名）
    url = Column(String, unique=True, index=True)           # 原始連結（去重鍵）
    platform = Column(String, nullable=True)                # youtube/instagram/tiktok/facebook/threads/other
    discord_message_id = Column(String, nullable=True, index=True)  # 卡片訊息 ID（reply 改名回查）
    created_at = Column(DateTime, default=func.now())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T app pytest tests/test_recipe_model.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 重啟讓 `create_all` 建表並驗證**

Run: `docker compose restart app`
Run:
```bash
docker compose exec -T app python -c "from models import Recipe; from database import SessionLocal; db=SessionLocal(); print('count =', db.query(Recipe).count()); db.close()"
```
Expected: `count = 0`（`main.py:25` 的 `Base.metadata.create_all` 已建 `recipes` 表）

- [ ] **Step 6: Commit**

```bash
git add models.py tests/test_recipe_model.py
git commit -m "feat(recipe): add Recipe model (url-unique)"
```

---

## Task 2: recipe/extract.py — parse_name_json（純函式 TDD）

**Files:**
- Create: `recipe/__init__.py`（空）
- Create: `recipe/extract.py`（先只放 `_RECIPE_PROMPT` + `parse_name_json`）
- Test: `tests/test_recipe_extract.py`

- [ ] **Step 1: Write the failing test**

建立空套件並寫測試：

```bash
mkdir -p /home/johnny/Desktop/linebot/recipe && : > /home/johnny/Desktop/linebot/recipe/__init__.py
```

`tests/test_recipe_extract.py`：

```python
from recipe.extract import parse_name_json


def test_parse_plain_json():
    assert parse_name_json('{"name":"蒜香奶油蝦"}') == "蒜香奶油蝦"


def test_parse_with_markdown_fences():
    raw = "```json\n{\"name\":\"番茄炒蛋\"}\n```"
    assert parse_name_json(raw) == "番茄炒蛋"


def test_parse_bare_triple_fence():
    raw = "```\n{\"name\":\"麻婆豆腐\"}\n```"
    assert parse_name_json(raw) == "麻婆豆腐"


def test_parse_missing_name_returns_empty():
    assert parse_name_json('{}') == ""


def test_parse_null_name_returns_empty():
    assert parse_name_json('{"name":null}') == ""


def test_parse_whitespace_stripped():
    assert parse_name_json('  {"name":"  滷肉飯  "}  ') == "滷肉飯"


def test_parse_invalid_json_returns_empty():
    assert parse_name_json("這不是 JSON") == ""
    assert parse_name_json("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T app pytest tests/test_recipe_extract.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'recipe.extract'`）

- [ ] **Step 3: Write minimal implementation**

`recipe/extract.py`：

```python
"""連結文字 blob → 乾淨菜名。

- parse_name_json：純函式，把 codex 回應字串解析成菜名（markdown 去殼、缺欄位/壞 JSON 回空字串）
- name_from_text：用 codex_text 從一段文字抽出菜名
"""
import json

from codex_cli import codex_text


_RECIPE_PROMPT = (
    "請從以下內容判斷這是哪一道料理，抽出乾淨的菜名。\n"
    "規則：去掉誇張標題/頻道名/emoji/集數/「教學」「食譜」等贅字，只留料理本身的名字；\n"
    "判斷不出菜名就回空字串。只回 JSON、不要 markdown 標籤：\n"
    '{{"name":"乾淨菜名(判斷不出就空字串)"}}\n\n'
    "內容：\n{text}"
)


def parse_name_json(raw: str) -> str:
    """把 codex 回應字串清成乾淨菜名。markdown 去殼、缺欄位/壞 JSON 皆回空字串、strip。"""
    t = (raw or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    try:
        d = json.loads(t.strip())
    except (ValueError, TypeError):
        return ""
    return (d.get("name") or "").strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T app pytest tests/test_recipe_extract.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add recipe/__init__.py recipe/extract.py tests/test_recipe_extract.py
git commit -m "feat(recipe): parse_name_json (markdown-strip, pure)"
```

---

## Task 3: recipe/extract.py — name_from_text（mock codex 邊界）

**Files:**
- Modify: `recipe/extract.py`（新增 `name_from_text`）
- Test: `tests/test_recipe_extract.py`（追加，mock `codex_text`）

- [ ] **Step 1: Write the failing test**

在 `tests/test_recipe_extract.py` 結尾追加（用 `monkeypatch` mock codex 邊界，不真的呼叫）：

```python
import recipe.extract as rx


def test_name_from_text_strips_to_clean_name(monkeypatch):
    monkeypatch.setattr(rx, "codex_text",
                        lambda prompt: '```json\n{"name":"奶油蒜香雞腿排"}\n```')
    assert rx.name_from_text("【超下飯】10分鐘奶油蒜香雞腿排教學 ft. 某頻道") == "奶油蒜香雞腿排"


def test_name_from_text_empty_when_codex_blank(monkeypatch):
    monkeypatch.setattr(rx, "codex_text", lambda prompt: '{"name":""}')
    assert rx.name_from_text("一段看不出菜名的旅遊 vlog 字幕") == ""


def test_name_from_text_passes_text_into_prompt(monkeypatch):
    seen = {}
    def fake(prompt):
        seen["prompt"] = prompt
        return '{"name":"x"}'
    monkeypatch.setattr(rx, "codex_text", fake)
    rx.name_from_text("獨特字串ABC123")
    assert "獨特字串ABC123" in seen["prompt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T app pytest tests/test_recipe_extract.py -v`
Expected: FAIL（`AttributeError: <module 'recipe.extract'> has no attribute 'name_from_text'`）

- [ ] **Step 3: Write minimal implementation**

在 `recipe/extract.py` 結尾（`parse_name_json` 之後）新增：

```python


def name_from_text(text: str) -> str:
    """一段文字 → 乾淨菜名（codex）。抽不到回空字串。"""
    return parse_name_json(codex_text(_RECIPE_PROMPT.format(text=text)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T app pytest tests/test_recipe_extract.py -v`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add recipe/extract.py tests/test_recipe_extract.py
git commit -m "feat(recipe): name_from_text via codex_text"
```

---

## Task 4: recipe/repo.py — to_dict + add_recipe（去重 + IntegrityError 防護）

**Files:**
- Create: `recipe/repo.py`
- Test: `tests/test_recipe_repo.py`（IntegrityError 分支以 stub session 模擬；不碰真 DB）

> `add_recipe` 的併發路徑（撞 `UNIQUE(url)`）以一個假的 SQLAlchemy session 物件在記憶體模擬：第一次 `commit()` 丟 `IntegrityError`，rollback 後 re-SELECT 命中既有列。DB 連線本身屬 I/O 邊界、不單測。

- [ ] **Step 1: Write the failing test**

`tests/test_recipe_repo.py`：

```python
import pytest
from sqlalchemy.exc import IntegrityError

import recipe.repo as repo


class FakeRec:
    def __init__(self, id, name, url, platform):
        self.id = id
        self.name = name
        self.url = url
        self.platform = platform
        self.discord_message_id = None
        self.created_at = None


class FakeQuery:
    def __init__(self, store):
        self._store = store
    def filter(self, *a, **k):
        return self
    def first(self):
        return self._store.get("hit")


class FakeSession:
    """模擬 add_recipe 需要的最小 session 介面。

    behavior:
      - 'clean'   ：SELECT 永遠落空、commit 成功 → 正常 INSERT 新建
      - 'race'    ：第一次 SELECT 落空（hit=None），commit 丟 IntegrityError，
                    rollback 後把 hit 換成既有列 → 走 IntegrityError 分支回 created=False
    """
    def __init__(self, mode):
        self.mode = mode
        self._hit_store = {"hit": None}
        self.added = []
        self.committed = 0
        self.rolled_back = 0
        self._existing = FakeRec(7, "既有菜", "https://x/dup", "youtube")

    def query(self, *a, **k):
        return FakeQuery(self._hit_store)
    def add(self, rec):
        self.added.append(rec)
    def commit(self):
        if self.mode == "race" and self.committed == 0:
            self.committed += 1
            raise IntegrityError("INSERT", {}, Exception("UNIQUE"))
        self.committed += 1
    def rollback(self):
        self.rolled_back += 1
        # 併發對手已寫入 → 之後 SELECT 命中既有列
        self._hit_store["hit"] = self._existing
    def refresh(self, rec):
        if rec.id is None:
            rec.id = 1
    def close(self):
        pass


def test_add_recipe_creates_when_clean(monkeypatch):
    sess = FakeSession("clean")
    monkeypatch.setattr(repo, "SessionLocal", lambda: sess)
    rec, created = repo.add_recipe("番茄炒蛋", "https://x/new", "youtube")
    assert created is True
    assert rec["name"] == "番茄炒蛋"
    assert rec["url"] == "https://x/new"
    assert len(sess.added) == 1


def test_add_recipe_integrity_error_returns_existing(monkeypatch):
    sess = FakeSession("race")
    monkeypatch.setattr(repo, "SessionLocal", lambda: sess)
    rec, created = repo.add_recipe("重複菜", "https://x/dup", "youtube")
    assert created is False
    assert rec["id"] == 7
    assert rec["name"] == "既有菜"
    assert sess.rolled_back == 1


def test_add_recipe_returns_existing_when_already_present(monkeypatch):
    sess = FakeSession("clean")
    sess._hit_store["hit"] = FakeRec(3, "舊菜", "https://x/old", "tiktok")
    monkeypatch.setattr(repo, "SessionLocal", lambda: sess)
    rec, created = repo.add_recipe("新名字會被忽略", "https://x/old", "tiktok")
    assert created is False
    assert rec["id"] == 3
    assert rec["name"] == "舊菜"
    assert sess.added == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T app pytest tests/test_recipe_repo.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'recipe.repo'`）

- [ ] **Step 3: Write minimal implementation**

`recipe/repo.py`（先放 import / `to_dict` / `add_recipe`；其餘函式 Task 5 再加）：

```python
"""Recipe 的 DB 存取（沿用 SessionLocal 慣例）。"""
import random

from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import Recipe


def to_dict(rec: Recipe) -> dict:
    """ORM → dict，供 embed 使用。"""
    return {
        "id": rec.id,
        "name": rec.name,
        "url": rec.url,
        "platform": rec.platform,
        "discord_message_id": rec.discord_message_id,
        "created_at": rec.created_at.isoformat() if rec.created_at else "",
    }


def _get_by_url(db, url: str):
    return db.query(Recipe).filter(Recipe.url == url).first()


def add_recipe(name: str, url: str, platform: str | None = None) -> tuple[dict, bool]:
    """以 url 去重。回 (dict, created)。

    SELECT→INSERT；併發下兩個 thread 可能都 SELECT 落空、都 INSERT，
    後者 commit 撞 UNIQUE(url) → rollback → 重新依 url SELECT → 當『已收錄過』回。
    """
    db = SessionLocal()
    try:
        existing = _get_by_url(db, url)
        if existing is not None:
            return to_dict(existing), False
        rec = Recipe(name=name, url=url, platform=platform)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T app pytest tests/test_recipe_repo.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add recipe/repo.py tests/test_recipe_repo.py
git commit -m "feat(recipe): add_recipe (url dedup + IntegrityError guard)"
```

---

## Task 5: recipe/repo.py — list/pick_random/delete/set_message_id/rename/get_by_message_id

**Files:**
- Modify: `recipe/repo.py`（新增其餘 6 個函式）
- Test: `tests/test_recipe_repo.py`（追加 `pick_random` 純函式測試）

> `pick_random` 的「載入後 `random.choice`」邏輯可純函式單測（mock `list_recipes` 回固定 list）。`list_recipes`/`delete_recipe`/`set_message_id`/`rename`/`get_by_message_id` 是 DB I/O 薄封裝，依 spec §9 不單測，但仍須完整實作 + 重啟手動驗證（Step 5）。

- [ ] **Step 1: Write the failing test**

在 `tests/test_recipe_repo.py` 結尾追加：

```python
def test_pick_random_empty(monkeypatch):
    monkeypatch.setattr(repo, "list_recipes", lambda: [])
    assert repo.pick_random() is None


def test_pick_random_single(monkeypatch):
    monkeypatch.setattr(repo, "list_recipes",
                        lambda: [{"id": 1, "name": "唯一菜", "url": "u"}])
    one = repo.pick_random()
    assert one["name"] == "唯一菜"


def test_pick_random_from_many(monkeypatch):
    rows = [{"id": i, "name": f"菜{i}", "url": f"u{i}"} for i in range(5)]
    monkeypatch.setattr(repo, "list_recipes", lambda: rows)
    picked = repo.pick_random()
    assert picked in rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T app pytest tests/test_recipe_repo.py -v`
Expected: FAIL（`AttributeError: module 'recipe.repo' has no attribute 'pick_random'`）

- [ ] **Step 3: Write minimal implementation**

在 `recipe/repo.py` 結尾（`add_recipe` 之後）新增：

```python


def list_recipes() -> list[dict]:
    """列出所有食譜，新到舊。"""
    db = SessionLocal()
    try:
        rows = db.query(Recipe).order_by(Recipe.created_at.desc()).all()
        return [to_dict(r) for r in rows]
    finally:
        db.close()


def pick_random() -> dict | None:
    """隨機抽一道（載入後 random.choice，不用 SQL random()）。空庫回 None。"""
    rows = list_recipes()
    return random.choice(rows) if rows else None


def delete_recipe(recipe_id: int) -> bool:
    """刪除一筆。True=刪了，False=查無。"""
    db = SessionLocal()
    try:
        rec = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if rec is None:
            return False
        db.delete(rec)
        db.commit()
        return True
    finally:
        db.close()


def set_message_id(recipe_id: int, message_id) -> None:
    """記下這筆 Recipe 對應的 Discord 卡片訊息 ID（給 reply 改名回查用）。"""
    db = SessionLocal()
    try:
        rec = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if rec is not None:
            rec.discord_message_id = str(message_id)
            db.commit()
    finally:
        db.close()


def rename(recipe_id: int, new_name: str) -> dict | None:
    """改菜名。查無回 None。"""
    db = SessionLocal()
    try:
        rec = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if rec is None:
            return None
        rec.name = (new_name or "").strip()
        db.commit()
        db.refresh(rec)
        return to_dict(rec)
    finally:
        db.close()


def get_by_message_id(message_id) -> dict | None:
    """從 Discord 卡片訊息 ID 反查 Recipe（純 getter，不改狀態）。查無回 None。"""
    db = SessionLocal()
    try:
        rec = (
            db.query(Recipe)
            .filter(Recipe.discord_message_id == str(message_id))
            .first()
        )
        return to_dict(rec) if rec is not None else None
    finally:
        db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T app pytest tests/test_recipe_repo.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 重啟並手動驗證 DB 路徑（add/list/pick/message_id/rename/get/delete）**

Run: `docker compose restart app`
Run:
```bash
docker compose exec -T app python -c "
from recipe.repo import add_recipe, list_recipes, pick_random, set_message_id, rename, get_by_message_id, delete_recipe
r1, c1 = add_recipe('番茄炒蛋', 'https://x/recipe1', 'youtube')
print('add1:', c1, r1['id'], r1['name'])
r2, c2 = add_recipe('重複', 'https://x/recipe1', 'youtube')
print('dup created? (應 False):', c2, 'name=', r2['name'])
set_message_id(r1['id'], 99999)
g = get_by_message_id(99999)
print('get_by_message_id:', g['id'], g['name'])
rn = rename(r1['id'], '招牌番茄炒蛋')
print('rename:', rn['name'])
print('list count:', len(list_recipes()))
print('pick:', pick_random()['name'])
print('delete:', delete_recipe(r1['id']))
print('delete miss:', delete_recipe(999999))
print('list after delete:', len(list_recipes()))
"
```
Expected：`add1: True ...` / `dup created? False name= 番茄炒蛋` / `get_by_message_id: <id> 番茄炒蛋` / `rename: 招牌番茄炒蛋` / `list count: 1` / `pick: 招牌番茄炒蛋` / `delete: True` / `delete miss: False` / `list after delete: 0`。

- [ ] **Step 6: Commit**

```bash
git add recipe/repo.py tests/test_recipe_repo.py
git commit -m "feat(recipe): repo list/pick_random/delete/rename/message_id getters"
```

---

## Task 6: recipe/ingest.py — from_url（gmaps 略過 + None-blob guard + 退用 blob 第一行）

**Files:**
- Create: `recipe/ingest.py`
- Test: `tests/test_recipe_ingest.py`（mock `classify_platform` / `food.extract.from_url` / `name_from_text` / `add_recipe` 邊界）

> `ingest.from_url` 的分支邏輯（gmaps 略過、None-blob guard、caption+blob 拼接、name 退用 blob 第一行、全空回 missing）是可單測的純編排，把所有 I/O 邊界 mock 掉。

- [ ] **Step 1: Write the failing test**

`tests/test_recipe_ingest.py`：

```python
import recipe.ingest as ing


def _no_add(*a, **k):
    raise AssertionError("不該呼叫 add_recipe")


def test_gmaps_is_skipped(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "gmaps")
    # gmaps 應在抽取前就被攔下，不該碰 from_url / add_recipe
    monkeypatch.setattr(ing, "_extract_from_url",
                        lambda url, platform: (_ for _ in ()).throw(AssertionError("不該抽取 gmaps")))
    monkeypatch.setattr(ing.repo, "add_recipe", _no_add)
    rec, reason = ing.from_url("https://maps.app.goo.gl/abc")
    assert rec is None
    assert "地點" in reason


def test_none_blob_with_no_caption_returns_missing(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "instagram")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: None)
    monkeypatch.setattr(ing.repo, "add_recipe", _no_add)
    rec, reason = ing.from_url("https://www.instagram.com/p/X/")
    assert rec is None
    assert "抽不到菜名" in reason


def test_name_from_text_used_when_blob_present(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: "一大段影片描述")
    monkeypatch.setattr(ing, "name_from_text", lambda text: "蒜香奶油蝦")
    captured = {}
    def fake_add(name, url, platform):
        captured.update(name=name, url=url, platform=platform)
        return {"id": 1, "name": name, "url": url, "platform": platform}, True
    monkeypatch.setattr(ing.repo, "add_recipe", fake_add)
    rec, reason = ing.from_url("https://youtu.be/abc")
    assert reason == ""
    assert rec["name"] == "蒜香奶油蝦"
    assert rec["_created"] is True
    assert captured["platform"] == "youtube"


def test_caption_prepended_to_blob(monkeypatch):
    seen = {}
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: "影片描述")
    def fake_name(text):
        seen["text"] = text
        return "x"
    monkeypatch.setattr(ing, "name_from_text", fake_name)
    monkeypatch.setattr(ing.repo, "add_recipe",
                        lambda name, url, platform: ({"id": 1, "name": name, "url": url}, True))
    ing.from_url("https://youtu.be/abc", caption="我的註解")
    assert "我的註解" in seen["text"]
    assert "影片描述" in seen["text"]


def test_falls_back_to_blob_first_line_when_name_empty(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url",
                        lambda url, platform: "宮保雞丁超下飯\n第二行廢話")
    monkeypatch.setattr(ing, "name_from_text", lambda text: "")  # codex 抽不出
    monkeypatch.setattr(ing.repo, "add_recipe",
                        lambda name, url, platform: ({"id": 1, "name": name, "url": url}, True))
    rec, reason = ing.from_url("https://youtu.be/abc")
    assert reason == ""
    assert rec["name"] == "宮保雞丁超下飯"  # blob 第一行


def test_all_empty_returns_missing(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: None)
    monkeypatch.setattr(ing, "name_from_text", lambda text: "")
    monkeypatch.setattr(ing.repo, "add_recipe", _no_add)
    rec, reason = ing.from_url("https://youtu.be/abc", caption="")
    assert rec is None
    assert "抽不到菜名" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T app pytest tests/test_recipe_ingest.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'recipe.ingest'`）

- [ ] **Step 3: Write minimal implementation**

`recipe/ingest.py`：

```python
"""連結 → 文字 blob → 乾淨菜名 → 入庫 Recipe 的 orchestrator。

回 (recipe_dict_or_None, missing_reason)：
- 非 None → 入庫成功，含 _created（True=新增 / False=已收錄過）
- None    → gmaps / 抽不到菜名（呼叫端回提示，必要時建 pending 卡）

最大化複用美食現成抽取基建：classify_platform + food.extract.from_url。
"""
from food.links import classify_platform
from food.extract import from_url as _extract_from_url
from recipe import repo
from recipe.extract import name_from_text


_GMAPS_REASON = "這看起來是地點不是食譜，要收店家請丟 #🍜-美食"
_NO_NAME_REASON = "抽不到菜名"


def from_url(url: str, *, caption: str = "") -> tuple[dict | None, str]:
    """從連結入庫食譜。caption 是使用者去 URL 後的文字註解（若有，優先併入）。"""
    platform = classify_platform(url)
    if platform == "gmaps":
        return None, _GMAPS_REASON

    try:
        blob = _extract_from_url(url, platform)
    except Exception as ex:
        return None, f"連結抽取失敗：{ex}"

    # None-blob guard（比照 food/ingest.py:77）
    pieces = [p for p in (caption.strip() if caption else "", blob or "") if p]
    text = "\n".join(pieces)

    name = ""
    if text:
        try:
            name = name_from_text(text)
        except Exception as ex:
            return None, f"菜名解析失敗：{ex}"

    # codex 抽不出 → 退用 blob 第一行當暫定名
    if not name and blob:
        name = blob.strip().splitlines()[0].strip()

    if not name:
        return None, _NO_NAME_REASON

    rec, created = repo.add_recipe(name, url, platform)
    rec["_created"] = created
    return rec, ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T app pytest tests/test_recipe_ingest.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add recipe/ingest.py tests/test_recipe_ingest.py
git commit -m "feat(recipe): ingest.from_url (gmaps skip, None-blob guard, blob fallback)"
```

---

## Task 7: discord_handler — embeds + 頻道分支 + handler + 3 個 slash 指令

**Files:**
- Modify: `discord_handler.py`（顏色常數區、embed builder 區、`on_message` 分流、新增 `_handle_recipe_message`、`_register_commands()` 內）

> slash 指令是主動行為、零風險。頻道分支放在 **food 分支之後、圖片附件分流之前**（spec §3/§6.1），避免食譜訊息夾帶縮圖被記帳搶走。`on_message` 改動最小、僅插入一個 `if`。

- [ ] **Step 1: 加 `COLOR_RECIPE` 常數**

在 `discord_handler.py` 既有顏色常數區（`COLOR_FOOD = 0xE67E22  # 美食橘` 那行，第 34 行）之後新增：

```python
COLOR_RECIPE  = 0x16A085   # 食譜青綠
```

- [ ] **Step 2: 加 4 個 recipe embed builder**

在 `discord_handler.py` 的 `food_map_embed()`（約第 273-278 行）之後新增。`r` 是 `recipe.repo.to_dict()` 的 dict：

```python
def recipe_card_embed(r: dict, *, created: bool = True) -> discord.Embed:
    title = (f"🍳 已收錄食譜：{r['name']}" if created
             else f"🍳 你已收錄過：{r['name']}")
    e = discord.Embed(title=title, color=COLOR_RECIPE)
    if r.get("platform"):
        e.add_field(name="📺 平台", value=r["platform"], inline=True)
    e.add_field(name="編號", value=f"#{r['id']}", inline=True)
    if r.get("url"):
        e.add_field(name="連結", value=r["url"], inline=False)
    e.set_footer(text="🔁 reply 這張卡片可改菜名")
    return e


def recipe_random_embed(r: dict) -> discord.Embed:
    e = discord.Embed(title=f"🍳 今天就煮：{r['name']}", color=COLOR_RECIPE)
    if r.get("url"):
        e.add_field(name="連結", value=f"[👉 點開照做]({r['url']})", inline=False)
    e.set_footer(text=f"編號 {r['id']}")
    return e


def recipe_list_embed(recipes: list[dict]) -> discord.Embed:
    e = discord.Embed(title=f"🍳 食譜清單（{len(recipes)} 道）", color=COLOR_RECIPE)
    if not recipes:
        e.description = "還沒收錄任何食譜，先去 #🍳-食譜 丟幾個連結。"
        return e
    lines = []
    for r in recipes[:25]:
        plat = f" `{r['platform']}`" if r.get("platform") else ""
        lines.append(f"`#{r['id']}` **{r['name']}**{plat}")
    e.description = "\n".join(lines)
    if len(recipes) > 25:
        e.set_footer(text=f"共 {len(recipes)} 道，只顯示前 25")
    return e


def recipe_missing_embed(reason: str) -> discord.Embed:
    e = discord.Embed(
        title="⚠️ 沒抽到菜名",
        description=reason or "抽不到菜名",
        color=COLOR_WARN,
    )
    e.set_footer(text="🔁 直接 reply 這張卡片給我一句菜名即可")
    return e
```

- [ ] **Step 3: 在 `on_message` 插入 recipe 頻道分支**

在 `discord_handler.py` 的 food 分支（約 332-335 行）之後、圖片附件分流（約 337 行 `# ── 2) 圖片附件分流`）之前插入。先在 `on_message` 開頭取頻道環境變數，把現有區塊：

```python
        food_chan = os.getenv("FOOD_INGEST_CHANNEL_ID") or ""
        rec_chan = os.getenv("DISCORD_RECORD_CHANNEL_ID") or ""
        ch_id = str(message.channel.id)

        # ── 1) 美食頻道：reply 補件 / 圖片或文字 ingest ─────────────
        if food_chan and ch_id == food_chan:
            await self._handle_food_message(message)
            return

        # ── 2) 圖片附件分流 ───────────────────────────────────────
```

改成（在 food 分支與圖片分流之間插入 recipe 分支；變數名用 `recipe_chan` 避免和記帳的 `rec_chan` 撞）：

```python
        food_chan = os.getenv("FOOD_INGEST_CHANNEL_ID") or ""
        recipe_chan = os.getenv("RECIPE_INGEST_CHANNEL_ID") or ""
        rec_chan = os.getenv("DISCORD_RECORD_CHANNEL_ID") or ""
        ch_id = str(message.channel.id)

        # ── 1) 美食頻道：reply 補件 / 圖片或文字 ingest ─────────────
        if food_chan and ch_id == food_chan:
            await self._handle_food_message(message)
            return

        # ── 1.5) 食譜頻道：reply 改名/補名 / 連結 ingest ────────────
        if recipe_chan and ch_id == recipe_chan:
            await self._handle_recipe_message(message)
            return

        # ── 2) 圖片附件分流 ───────────────────────────────────────
```

- [ ] **Step 4: 新增 `_handle_recipe_message`**

在 `discord_handler.py` 的 `_handle_food_message`（結束於約第 480 行）之後、`on_raw_reaction_add`（約第 482 行）之前新增。複用 `recipe.repo` / `recipe.ingest` / `food.pending`（共用全域 dict，message id 全域唯一故不互撞）：

```python
    async def _handle_recipe_message(self, message: discord.Message):
        from recipe import ingest as recipe_ingest, repo as recipe_repo

        # ── a/b/c) reply：先試改名(get_by_message_id) → 再試補名(pending) ──
        ref = getattr(message, "reference", None)
        if ref and ref.message_id:
            reply_text = (message.content or "").strip()
            # a) 命中既有 Recipe 卡片 → 改名
            existing = recipe_repo.get_by_message_id(ref.message_id)
            if existing and reply_text:
                updated = recipe_repo.rename(existing["id"], reply_text)
                if updated:
                    sent = await message.channel.send(
                        embed=recipe_card_embed(updated, created=False)
                    )
                    recipe_repo.set_message_id(updated["id"], sent.id)
                return
            # b) 命中 pending（先前抽不到菜名）→ 用 reply 文字 + source_url 建檔
            ctx = pending.get(ref.message_id)
            if ctx and reply_text:
                pending.consume(ref.message_id)
                source_url = ctx.get("source_url")
                # platform 由 source_url 重算（pending 沒存 platform），保住卡片平台標籤
                from food.links import classify_platform
                platform = classify_platform(source_url) if source_url else None
                async with message.channel.typing():
                    rec, created = recipe_repo.add_recipe(
                        reply_text, source_url, platform
                    )
                rec["_created"] = created
                sent = await message.channel.send(
                    embed=recipe_card_embed(rec, created=rec.get("_created", True))
                )
                recipe_repo.set_message_id(rec["id"], sent.id)
                return
            # c) 兩者皆 miss（重啟丟 pending／卡片已被刪）
            if existing is None and ctx is None:
                await message.channel.send(
                    "這張卡片資料過期了，直接重貼連結就好 🍳"
                )
                return

        # ── 連結 ingest（一連結一卡，多連結平行）─────────────────
        links = detect_links(message.content or "")
        if links:
            caption = strip_urls(message.content or "")
            async with message.channel.typing():
                results = await asyncio.gather(
                    *[asyncio.to_thread(recipe_ingest.from_url, lk["url"], caption=caption)
                      for lk in links],
                    return_exceptions=True,
                )
                for lk, res in zip(links, results):
                    url = lk["url"]
                    platform = lk["platform"]
                    if isinstance(res, Exception):
                        rec, reason = None, f"處理失敗：{res}"
                    else:
                        rec, reason = res
                    if rec:
                        sent = await message.channel.send(
                            embed=recipe_card_embed(rec, created=rec.get("_created", True))
                        )
                        recipe_repo.set_message_id(rec["id"], sent.id)
                    else:
                        sent = await message.channel.send(embed=recipe_missing_embed(reason))
                        # 只有「抽不到菜名」才需 reply 補名；gmaps 等不建 pending
                        if reason == "抽不到菜名":
                            pending.remember(
                                sent.id,
                                original_message_id=message.id,
                                source_url=url,
                                missing_reason=reason,
                            )
            return

        # ── 無連結、非 reply（純文字 / 純圖片）→ 回提示，不建檔 ──
        await message.channel.send("這個頻道請丟食譜連結 🍳")
```

> 註：`pending.remember` 的簽名是 `remember(bot_message_id, *, original_message_id, raw_text="", source_url=None, attachment_url=None, missing_reason="")`，無 `platform` 參數；故 reply 補名分支**不從 pending 取 platform**，改用 `classify_platform(source_url)` 由連結重算（純函式、無 I/O），補名卡片即可保留正確平台標籤；`source_url` 萬一為空則 `platform=None`，`add_recipe` 接受。

- [ ] **Step 5: 在 `_register_commands()` 內加 3 個食譜指令**

在 `discord_handler.py` 的 `cmd_food_map`（約 685-689 行）之後、`cmd_test_weekly`（約 691 行）之前新增：

```python
        @tree.command(name="隨機食譜", description="從收錄的食譜裡隨機抽一道")
        async def cmd_recipe_random(ix: discord.Interaction):
            await ix.response.defer()
            from recipe.repo import pick_random
            r = pick_random()
            if not r:
                await ix.followup.send("還沒收錄任何食譜，先去 #🍳-食譜 丟幾個連結 🍳")
                return
            await ix.followup.send(embed=recipe_random_embed(r))

        @tree.command(name="食譜清單", description="列出所有收錄的食譜")
        async def cmd_recipe_list(ix: discord.Interaction):
            await ix.response.defer()
            from recipe.repo import list_recipes
            await ix.followup.send(embed=recipe_list_embed(list_recipes()))

        @tree.command(name="食譜刪除", description="刪除一筆食譜")
        @app_commands.describe(編號="食譜編號")
        async def cmd_recipe_delete(ix: discord.Interaction, 編號: int):
            await ix.response.defer()
            from recipe.repo import delete_recipe
            ok = delete_recipe(編號)
            if ok:
                await ix.followup.send(f"🗑️ 已刪除 #{編號}")
            else:
                await ix.followup.send(embed=error_embed(f"找不到編號 {編號}"))
```

- [ ] **Step 6: 重啟並驗證 import / 指令同步無誤**

Run: `docker compose restart app`
Run: `docker compose logs app --tail=8`
Expected：無 import / SyntaxError，看到 `🐉 Discord Bot 已上線`。然後在 Discord 確認 `/隨機食譜`、`/食譜清單`、`/食譜刪除` 出現在指令選單。

- [ ] **Step 7: Commit**

```bash
git add discord_handler.py
git commit -m "feat(recipe): discord channel branch + handler + 3 slash commands + embeds"
```

---

## Task 8: 環境變數 + 真實連結實測 + 文件同步

**Files:**
- Modify: `docker-compose.yml`（app service environment）
- Modify: `.env`
- Modify: `README.md`、`CODEBASE.md`

> spec §11：`RECIPE_INGEST_CHANNEL_ID` 未設則食譜分支不啟用（`recipe_chan` 為空 → `if recipe_chan and ...` 短路），不影響美食/記帳。

- [ ] **Step 1: docker-compose.yml 加環境變數**

在 `docker-compose.yml` app service 的 `environment:` 區塊，`FOOD_INGEST_CHANNEL_ID=${FOOD_INGEST_CHANNEL_ID}` 那行之後加一行：

```yaml
      - RECIPE_INGEST_CHANNEL_ID=${RECIPE_INGEST_CHANNEL_ID:-}
```

- [ ] **Step 2: .env 加變數**

在 `.env` 的 `FOOD_INGEST_CHANNEL_ID=...` 那行之後加（值填 `#🍳-食譜` 頻道 ID；建立頻道後填入，沒填則分支不啟用）：

```
RECIPE_INGEST_CHANNEL_ID=<你的食譜頻道 ID>
```

- [ ] **Step 3: 重啟讓新環境變數生效，跑全測試**

Run: `docker compose restart app`
Run: `docker compose exec -T app pytest tests/ -v`
Expected：全綠，含 `test_recipe_model` / `test_recipe_extract`（10）/ `test_recipe_repo`（6）/ `test_recipe_ingest`（6），且既有 food/report 測試不受影響。

- [ ] **Step 4: Discord 真實連結實測（spec §12：先寫一版再用真實 YT/IG 連結收斂菜名強度）**

在 `#🍳-食譜` 頻道實測一輪：
1. 丟一條 YouTube 食譜連結 → 應回 `🍳 已收錄食譜：<乾淨菜名>` 卡片，footer 有「reply 可改菜名」。
2. 同一條再丟一次 → 應回 `🍳 你已收錄過：<菜名>`（url 去重 / created=False）。
3. reply 那張卡片打一個新菜名 → 應回 `🍳 你已收錄過：<新菜名>`（rename 成功）。
4. 丟一個 Google Maps 連結 → 應回 `⚠️ 沒抽到菜名` + 「這看起來是地點不是食譜」。
5. 在頻道只打純文字（無連結）→ 應回「這個頻道請丟食譜連結 🍳」，不建檔。
6. `/隨機食譜` → 抽到一道、`/食譜清單` → 看到、`/食譜刪除 編號:<id>` → 回「已刪除」。

> 若步驟 1 的菜名仍夾帶頻道名/集數等贅字，回 `recipe/extract.py` 的 `_RECIPE_PROMPT` 收斂清理規則（這是 spec §12 預期的迭代點）。

- [ ] **Step 5: 清掉實測資料**

Run:
```bash
docker compose exec -T app python -c "from database import SessionLocal; from models import Recipe; db=SessionLocal(); db.query(Recipe).delete(); db.commit(); db.close(); print('cleared')"
```
Expected: `cleared`

- [ ] **Step 6: 更新 README / CODEBASE**

`README.md`：
- Discord slash 指令表新增 `/隨機食譜`、`/食譜清單`、`/食譜刪除 編號` 三列（說明：食譜收錄 — 丟連結到 #🍳-食譜 自動抽菜名，`/隨機食譜` 解決今天煮什麼）。
- 環境變數區新增 `RECIPE_INGEST_CHANNEL_ID`（`#🍳-食譜` 頻道 ID，未設則食譜分支不啟用）。

`CODEBASE.md`：
- File Map 新增 `recipe/`（`extract`/`repo`/`ingest`）與 `Recipe` 表（`recipes`，`url` 唯一去重）。
- 註明 `recipe` 複用 `food.links` / `food.extract.from_url` / `food.pending`；`discord_handler` 新增 `RECIPE_INGEST_CHANNEL_ID` 分支（緊接 food 分支後、圖片分流前）。
- slash 指令總數相應 +3。

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml .env README.md CODEBASE.md
git commit -m "feat(recipe): RECIPE_INGEST_CHANNEL_ID env + docs (README/CODEBASE)"
```

---

## 完成標準

- [ ] `recipes` 表存在、`url` UNIQUE 生效。
- [ ] `pytest tests/` 全綠（含 `test_recipe_*` 四檔）。
- [ ] Discord：丟連結到 #🍳-食譜 自動抽菜名建卡、同 url 去重標「已收錄過」、reply 改名、gmaps 回提示不建檔、純文字回提示；`/隨機食譜` 抽一道、`/食譜清單` 列出、`/食譜刪除` 刪除。
- [ ] `RECIPE_INGEST_CHANNEL_ID` 未設時食譜分支不啟用，完全沒動 `on_message` 記帳/美食既有行為。
- [ ] gmaps 略過、None-blob guard、`add_recipe` IntegrityError-on-UNIQUE(url)、`pick_random` 走 `random.choice`、reply 改名走新 `get_by_message_id`、補名共用 `food.pending`、頻道閘控 reply 處理 — 全部按 spec 實作。
