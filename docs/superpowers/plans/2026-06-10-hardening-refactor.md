# 後端強化重構 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把審查核可的五項改進落地：BASE_URL 環境變數化、DB session 統一管理、拆分 discord_handler.py、food photos 一致性+外鍵、enrich API quota 防護。

**Architecture:** 全部是對既有功能的強化/重組，不新增使用者可見功能。拆分 discord_handler 採新 package `discordbot/`（不能叫 `discord`，會遮蔽 discord.py 套件）。DB migration 沿用 main.py 啟動時自動檢查的既有模式。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL 15 / discord.py / pytest（在 app 容器內跑：`docker compose exec -T app pytest tests/ -q`）

**前置狀態：** 工作樹有未 commit 的照片/PWA 後端程式（photos.py、enrich.py、places.py 新函式、models.py FoodPhoto、main.py mounts），Task 0 先把它們以綠燈狀態 commit 進來，後續任務在其上強化。frontend/ 仍在開發中，**不 commit**。

---

### Task 0: 把既有未 commit 的照片/PWA 後端程式以綠燈狀態入庫

**Files:**
- Modify: `tests/test_food_map_data.py`（期望欄位集合加 `city`、`place_id`）
- Modify: `main.py:59-63`（mount 加目錄存在判斷，沒有 frontend/dist 也能啟動）
- Commit: `.gitignore`, `media/.gitkeep`, `food/map_data.py`, `food/places.py`, `food/repo.py`, `food/photos.py`, `food/enrich.py`, `models.py`, `requirements.txt`, `routes/food_map.py`, `discord_handler.py`（/m/ 連結一行）, `main.py`

- [ ] **Step 1: 修 test_food_map_data 期望欄位**：在斷言的欄位集合加入 `"city"`, `"place_id"`。
- [ ] **Step 2: main.py mount 加守門**

```python
# 手機版 PWA（前端 build 後的靜態檔）；對外經 ngrok 走 /m/。沒 build 過則跳過（後端可獨立啟動）
if os.path.isdir("frontend/dist"):
    app.mount("/m", StaticFiles(directory="frontend/dist", html=True), name="mobile")

# 使用者上傳的店家照片（bot/app 兩條路都寫到 media/）
os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")
```

- [ ] **Step 3: 跑測試** `docker compose exec -T app pytest tests/ -q` → 182 passed
- [ ] **Step 4: Commit**（訊息 `feat(food): 照片庫/enrich/地圖資料 PWA 後端接點（補測試+啟動守門）`；不包含 frontend/）

### Task 1: BASE_URL 環境變數化

**Files:**
- Modify: `line_handler.py:12-13`, `discord_handler.py:26-27`, `docker-compose.yml`(app environment)

- [ ] **Step 1:** 兩處改成：

```python
BASE_URL = os.getenv("BASE_URL", "https://your-ngrok-domain.ngrok-free.dev").rstrip("/")
```

（保留現域名當預設值 → 不設定 .env 也不破壞現行為；line_handler 已 import os）

- [ ] **Step 2:** docker-compose.yml app environment 加 `- BASE_URL=${BASE_URL:-https://your-ngrok-domain.ngrok-free.dev}`
- [ ] **Step 3:** 跑測試（迴歸）→ commit `refactor: BASE_URL 改讀環境變數（預設沿用 ngrok 保留域名）` + README/CODEBASE 環境變數段補 BASE_URL

### Task 2: DB session 統一管理（helpers + routes）

**Files:**
- Modify: `database.py`（加 `get_db` 與 `session_scope`）
- Modify: `routes/record.py`, `routes/report.py`（改用 `Depends(get_db)`）
- 注意：core.py 的 55 處沿用點**這次不動**——core.py 零測試，先在測試缺口報告排補測，有保護網再做機械式轉換。

- [ ] **Step 1: database.py 加**

```python
from contextlib import contextmanager

def get_db():
    """FastAPI dependency：yield 一個 session，請求結束自動 close。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def session_scope():
    """一般程式用的 context manager：成功 commit、例外 rollback、必 close。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

- [ ] **Step 2:** routes/record.py 三個 endpoint 簽名加 `db: Session = Depends(get_db)`，刪掉手寫 `SessionLocal()/finally close`（保留 rollback→HTTPException 邏輯）。routes/report.py 同。
- [ ] **Step 3:** 跑測試 → commit `refactor(db): get_db/session_scope helpers + routes 改依賴注入` + CODEBASE Key Patterns 段更新

### Task 3: 拆分 discord_handler.py → discordbot/ package

**Files:**
- Create: `discordbot/__init__.py`（re-export 對外 API）
- Create: `discordbot/embeds.py`（顏色常數、fmt_money/fmt_dt、全部 embed builder、_build_items_embed；= 原 42-382 + 948-967 行）
- Create: `discordbot/bridge.py`（_bot_instance、set_bot、_post_embeds_sync；= 原 920-945 行）
- Create: `discordbot/reports.py`（_query_period、_aggregate_groups、_generate_ai_comment、notify_invoice_sync、notify_weekly_summary、notify_monthly_summary；= 原 970-1339 行）
- Create: `discordbot/ingest_handlers.py`（_handle_food_message、_handle_recipe_message、_send_recipe_card、_do_image_recording、_HINT_DEBOUNCE；改成收 message 的 module 函式；= 原 446-644 行）
- Create: `discordbot/commands.py`（`register_commands(bot)`；= 原 666-909 行的 28 個 slash command）
- Create: `discordbot/bot.py`（MoneyBot：on_ready/on_message/on_raw_reaction_add + create_discord_bot；= 原 387-444、646-664、912-915 行）
- Modify: `main.py:16-21`（import 改 `from discordbot import ...`）
- Delete: `discord_handler.py`

**規則：函式內容逐字搬移、不改邏輯**；只改 (1) module 間 import、(2) `self._handle_food_message(message)` → `await ingest_handlers.handle_food_message(message)` 這類呼叫點。BASE_URL 常數放 commands.py（唯二使用點都在 slash commands）。

- [ ] **Step 1:** 依上述建檔搬移
- [ ] **Step 2:** `__init__.py` re-export：create_discord_bot、set_bot、notify_invoice_sync、notify_weekly_summary、notify_monthly_summary
- [ ] **Step 3:** 全 repo grep `discord_handler` 確認無殘留 import；`docker compose exec -T app python -c "import discordbot, main"` 驗證可載入
- [ ] **Step 4:** 跑測試 → commit `refactor(discord): 拆 discord_handler.py 為 discordbot/ package（六模組、邏輯不變）` + README/CODEBASE File Map 更新

### Task 4: food photos 一致性 + 外鍵

**Files:**
- Modify: `models.py:83`（FoodPhoto.food_place_id 加 ForeignKey + CASCADE）
- Modify: `main.py`（啟動 migration：清孤兒列 + 補 FK constraint，沿用既有欄位檢查模式）
- Modify: `food/photos.py`（add_photo 失敗回滾檔案；delete_photo 刪檔失敗記 warning；新增 delete_files_for_place）
- Modify: `food/repo.py:delete_place`（先刪照片檔案再刪店）
- Test: `tests/test_food_photos.py`（新檔）

- [ ] **Step 1: models.py**

```python
from sqlalchemy import ForeignKey
food_place_id = Column(Integer, ForeignKey("food_places.id", ondelete="CASCADE"),
                       index=True, nullable=False)
```

- [ ] **Step 2: main.py 啟動 migration**（在既有欄位檢查 try 區塊內延伸）

```python
fks = _inspector.get_foreign_keys("food_photos") if _inspector.has_table("food_photos") else None
if fks is not None and not fks:
    _conn.execute(_text(
        "DELETE FROM food_photos WHERE food_place_id NOT IN (SELECT id FROM food_places)"))
    _conn.execute(_text(
        "ALTER TABLE food_photos ADD CONSTRAINT fk_food_photos_place "
        "FOREIGN KEY (food_place_id) REFERENCES food_places(id) ON DELETE CASCADE"))
    _conn.commit()
    print("✅ food_photos 已補上 FK（含孤兒清理）")
```

- [ ] **Step 3: 先寫失敗測試**（FakeSession 模式同 tests/test_recipe_repo.py；MEDIA_ROOT 用 monkeypatch 指到 tmp_path）：
  - `test_add_photo_db_fail_removes_file`：commit 丟例外 → 檔案被刪掉、例外往外拋
  - `test_add_photo_bad_ext_falls_back_jpg`
  - `test_delete_photo_missing_file_still_deletes_row`
  - `test_delete_files_for_place_removes_dir`
- [ ] **Step 4: 實作** photos.py：

```python
def add_photo(...):
    ...寫檔同現行...
    db = SessionLocal()
    try:
        rec = FoodPhoto(...)
        db.add(rec); db.commit(); db.refresh(rec)
        return {...}
    except Exception:
        db.rollback()
        try: os.remove(os.path.join(MEDIA_ROOT, rel_path))
        except OSError: pass
        raise
    finally:
        db.close()

def delete_files_for_place(food_place_id: int) -> None:
    """刪掉某店整個照片資料夾（配合 FK CASCADE：DB 列自動刪、檔案這裡刪）。"""
    import shutil
    d = os.path.join(MEDIA_ROOT, "food", str(food_place_id))
    shutil.rmtree(d, ignore_errors=True)
```

delete_photo 的 `except OSError: pass` 改成 `print(f"⚠️ 照片檔案刪除失敗（DB 列已刪）：{rec.path}")` 後繼續。
- [ ] **Step 5:** repo.delete_place 刪列前呼叫 `photos.delete_files_for_place(food_id)`
- [ ] **Step 6:** 跑測試 → commit `fix(food): FoodPhoto 外鍵+CASCADE、照片檔案/DB 一致性（含測試）` + CODEBASE DB Schema 更新

### Task 5: enrich quota 防護

**Files:**
- Modify: `food/places.py`（module 級 API 呼叫計數：search_text/fetch_reviews/fetch_place_photo 各 +1，photo 的 media 下載再 +1；`api_call_count()` 取值）
- Modify: `food/enrich.py`（`backfill_all(max_api_calls: int = 200)`：每家處理前檢查預算，超了就停＋log 剩幾家沒跑；錯誤從 print 改 `traceback.print_exc()` 保留堆疊）
- Test: `tests/test_food_enrich.py`（新檔，monkeypatch places 函式）

- [ ] **Step 1: 先寫失敗測試**：
  - `test_backfill_stops_at_budget`：mock 讓每家吃 3 個 call、預算 7 → 只處理 2 家、log 報告剩餘家數
  - `test_enrich_skips_when_already_has_recommended`
  - `test_enrich_skips_photo_when_google_photo_exists`
- [ ] **Step 2: 實作** places.py 計數器：

```python
_api_calls = 0
def _count(n: int = 1) -> None:
    global _api_calls
    _api_calls += n
def api_call_count() -> int:
    return _api_calls
```

enrich.py：

```python
def backfill_all(max_api_calls: int = 200) -> None:
    from food import places
    ...
    start = places.api_call_count()
    for i, (fid, pid, name, cur) in enumerate(rows, 1):
        if places.api_call_count() - start >= max_api_calls:
            print(f"⛔ 已達 API 預算 {max_api_calls}，剩 {total - i + 1} 家未跑（改天再跑即續）", flush=True)
            break
        ...
```

- [ ] **Step 3:** 跑測試 → commit `feat(food): enrich backfill 加 API 呼叫預算 + 錯誤保留堆疊（含測試）`

### Task 6: 測試缺口 + 功能建議 HTML 報告

**Files:**
- Create: `docs/audit/2026-06-10-test-gaps-and-features.html`（自包含、無外部資源、繁中、手機可讀）

內容：(A) 測試缺口排序表（core.py > routes 整合 > auth > recurring > einvoice 整合），(B) 功能建議卡片（照片來源標示、/美食補強 指令、PWA manifest/SW、PWA 長效 device token、備份加密等），各附價值/工作量。

- [ ] **Step 1:** 寫 HTML → commit `docs: 測試缺口與功能建議報告（2026-06-10）`

### 收尾

- [ ] 全測試綠 + `python -c "import main"` 容器內可載入
- [ ] README.md / CODEBASE.md 與最終結構一致（每個 commit 已分次更新）
- [ ] 提醒使用者：容器跑的是舊 code，要 `docker compose restart app` 才生效；frontend/ 仍未 commit（PWA 開發中）
