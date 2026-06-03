# 美食批次匯入（Food Batch Import）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `#🍜-美食` 頻道一次貼進「markdown 待辦清單」（多行店名）就批次匯進美食庫，回一張智慧總結卡（✅ 高信心 / ⚠️ 需確認 / ❌ 找不到），並新增 `/美食刪除` 修正猜錯分店。

**Architecture:** 完全沿用 `FoodPlace` ORM（**不動資料模型**）。新增純函式 `extract.parse_place_list`（一次 codex 批解析整份清單 → 對齊行序的 `list[fields]`）、`ingest.strip_checkbox`（剝勾選框前綴 → `(status, content)`）、`ingest.batch_from_text`（async orchestrator：行數偵測 ≥2、60 行上限、`asyncio.Semaphore` 限流包住 `await asyncio.to_thread`、**collect-then-dedup-then-upsert** 修 TOCTOU、信心分桶）、`repo.delete_place`（→ `bool`）；`discord_handler` 在 `_handle_food_message` 純文字分支內插入批次偵測，新增 `food_batch_summary_embed` 與 `/美食刪除`。複用既有 `places.search_text`、`repo.upsert_place`（**keyword-only 參數**）、`repo.set_visited`。

**Tech Stack:** Python 3.11、asyncio（`Semaphore` / `gather` / `to_thread`）、SQLAlchemy、本機 codex CLI（`codex_cli.codex_text`，blocking subprocess、timeout 180s）、Google Places API (New)（`GOOGLE_PLACES_SERVER_KEY`）、discord.py、pytest。

> 對應 spec：`docs/superpowers/specs/2026-06-02-food-batch-import-design.md`（2026-06-03 經多 agent 對照真實碼審核強化）。
> 本計畫**不含**：先預覽再確認的互動流程、檔案/截圖批次、Google 收藏清單匯入、新增資料表/欄位、批次雷點摘要（刻意只 `search_text`+`upsert_place`，等同 `/美食新增`）。
> 專案慣例：每次 commit 同步更新 `README.md` / `CODEBASE.md`（見 Task 7）。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `food/ingest.py` | 修改 | 新增純函式 `strip_checkbox()`、`bucket_line()`、`dedupe_resolved()`，與 async orchestrator `batch_from_text()`（行數偵測、60 行上限、Semaphore 限流、collect-then-dedup-then-upsert、分桶） |
| `food/extract.py` | 修改 | 新增 `parse_place_list(lines) -> list[dict]`（一次 codex 批解析整份清單，對齊行序）+ `_PLACE_LIST_PROMPT` + `parse_place_list_json()`（純函式，可單測：解析 codex 回的 JSON 陣列） |
| `food/repo.py` | 修改 | 新增 `delete_place(food_id) -> bool`（刪到回 True、查無回 False） |
| `discord_handler.py` | 修改 | `_handle_food_message` 純文字分支內插入批次偵測（≥2 非空行）、`food_batch_summary_embed()` builder、`/美食刪除` slash 指令 |
| `README.md` | 修改 | slash 指令表新增 `/美食刪除`；說明批次匯入用法 |
| `CODEBASE.md` | 修改 | File Map 標註批次匯入、slash 指令數 +1 |
| `tests/test_food_batch.py` | 建立 | 批次純函式單元測試（行數判定、strip_checkbox、parse_place_list_json、上限截斷、分桶、place_id 去重+狀態升級） |

> **I/O 邊界不單測**（spec §9）：`extract.parse_place_list`（codex 子程序）、`places.search_text`（Google）、`repo.delete_place`/`upsert_place`/`set_visited`（DB）、Discord 屬 I/O 邊界，以薄封裝隔離、手動驗證，不寫 pytest。純函式（行數判定、`strip_checkbox`、`parse_place_list_json`、截斷、`bucket_line`、`dedupe_resolved`）走 pytest。

測試執行：`docker compose exec -T app pytest tests/test_food_batch.py -v`
套用程式變更：`docker compose restart app`（純 .py 改動，bind mount + 主進程重啟即重新 import）

> **依賴方向提醒**：`batch_from_text` 內 `await asyncio.to_thread(...)` 包同步函式 `_resolve_one`，`Semaphore` **只放在 async 層**（`async with sem: await asyncio.to_thread(...)`），絕不放進同步函式體（sync thread 無法 `async with` asyncio 物件）。先收集 `resolved` → 程序內依 `place_id` 去重 → 才統一 `upsert_place`（修 TOCTOU，spec §6.1）。

---

## Task 1: `extract.parse_place_list` — 一次 codex 批解析（純函式 JSON 解析可單測）

**Files:**
- Modify: `food/extract.py`（檔尾新增 `_PLACE_LIST_PROMPT`、`parse_place_list_json`、`parse_place_list`）
- Test: `tests/test_food_batch.py`（新建，先測 `parse_place_list_json` 純函式）

> `parse_place_list`（呼叫 `codex_text`）是 I/O 邊界、不單測；但把「解析 codex 回的 JSON 陣列 → 對齊行序 list[fields]」抽成純函式 `parse_place_list_json(raw, n)`，單測它（補空、截斷 markdown、長度對齊、壞 JSON）。

- [ ] **Step 1: 寫失敗測試（新建 `tests/test_food_batch.py`，先放 `parse_place_list_json` 測試）**

完整檔案內容（後續 Task 會往這個檔案追加更多測試函式，本步先建立並只放本任務測試）：

```python
from food.extract import parse_place_list_json


def test_parse_place_list_json_basic():
    raw = (
        '[{"name":"鼎泰豐","area":"信義","recommended_items":"小籠包","cuisine_type":"中式"},'
        '{"name":"映客牛蒡天婦羅","area":"台中","recommended_items":"","cuisine_type":"天婦羅"}]'
    )
    out = parse_place_list_json(raw, 2)
    assert len(out) == 2
    assert out[0] == {"name": "鼎泰豐", "area": "信義",
                      "recommended_items": "小籠包", "cuisine_type": "中式"}
    assert out[1]["name"] == "映客牛蒡天婦羅"
    assert out[1]["recommended_items"] == ""


def test_parse_place_list_json_strips_markdown_fence():
    raw = '```json\n[{"name":"A"}]\n```'
    out = parse_place_list_json(raw, 1)
    assert out[0]["name"] == "A"
    # 缺欄位補空字串
    assert out[0]["area"] == ""
    assert out[0]["recommended_items"] == ""
    assert out[0]["cuisine_type"] == ""


def test_parse_place_list_json_pads_short_array_with_empty():
    # codex 只回 1 筆，但有 3 行 → 補到 3 筆空 name
    raw = '[{"name":"只有一家","area":"台北"}]'
    out = parse_place_list_json(raw, 3)
    assert len(out) == 3
    assert out[0]["name"] == "只有一家"
    assert out[1] == {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}
    assert out[2]["name"] == ""


def test_parse_place_list_json_truncates_long_array():
    # codex 回比 n 多 → 截到 n
    raw = '[{"name":"X"},{"name":"Y"},{"name":"Z"}]'
    out = parse_place_list_json(raw, 2)
    assert len(out) == 2
    assert [o["name"] for o in out] == ["X", "Y"]


def test_parse_place_list_json_whitespace_stripped_per_field():
    raw = '[{"name":"  甲  ","area":" 台中 "}]'
    out = parse_place_list_json(raw, 1)
    assert out[0]["name"] == "甲"
    assert out[0]["area"] == "台中"


def test_parse_place_list_json_bad_json_returns_all_empty():
    # 整段 JSON 壞掉 → 回 n 筆全空（落 ❌，不假裝成功）
    out = parse_place_list_json("這不是 JSON", 2)
    assert len(out) == 2
    assert all(o["name"] == "" for o in out)
    assert out[0] == {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -v`
Expected: FAIL（`ImportError: cannot import name 'parse_place_list_json' from 'food.extract'`）

- [ ] **Step 3: 在 `food/extract.py` 檔尾新增 prompt + 兩個函式**

在 `food/extract.py` 最末端（`deep_extract_via_codex` 之後）追加：

```python
_PLACE_LIST_PROMPT = (
    "以下每行是一家店（已去掉清單勾選框）。請逐行擷取店家資訊，"
    "回一個 JSON 陣列、長度等於行數、順序對齊每一行，只回 JSON、不要 markdown 標籤：\n"
    '[{"name":"店名(該行抽不到就空字串)","area":"區域提示(縣市/城市/分店);沒有就空字串",'
    '"recommended_items":"該行明確稱讚/必點的具體菜名;沒有就空字串,不要放料理類別",'
    '"cuisine_type":"料理類型(例:拉麵、咖啡、火鍋);可空"}]\n\n'
    "注意:\n"
    "- 每行尾端可能有括號(可能沒收尾,例如「映客 (台中」),括號內若是地區/分店填 area、"
    "若是推薦菜填 recommended_items、若是純感想則忽略。\n"
    "- 陣列長度必須等於下方行數,第 i 個物件對應第 i 行;某行抽不出店名就回 name 空字串。\n"
    "- recommended_items 必須是明確被稱讚/必點的具體菜名;只列料理類別就留空、填進 cuisine_type。\n\n"
    "店家清單(每行一家)：\n{lines}"
)


def _empty_fields() -> dict:
    return {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}


def parse_place_list_json(raw: str, n: int) -> list[dict]:
    """把 codex 回的 JSON 陣列字串清成『對齊 n 行』的 list[fields]（純函式，可單測）。

    - 去 markdown 包覆；每欄 strip、缺欄位補空字串。
    - 陣列短於 n → 補空 name；長於 n → 截到 n。
    - 整段 JSON 壞掉/非 list → 回 n 筆全空（落 ❌，不假裝成功）。
    """
    t = (raw or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    try:
        data = json.loads(t.strip())
    except Exception:
        data = None
    if not isinstance(data, list):
        return [_empty_fields() for _ in range(n)]
    out: list[dict] = []
    for d in data[:n]:
        if not isinstance(d, dict):
            out.append(_empty_fields())
            continue
        out.append({
            "name": (d.get("name") or "").strip(),
            "area": (d.get("area") or "").strip(),
            "recommended_items": (d.get("recommended_items") or "").strip(),
            "cuisine_type": (d.get("cuisine_type") or "").strip(),
        })
    while len(out) < n:
        out.append(_empty_fields())
    return out


def parse_place_list(lines: list[str]) -> list[dict]:
    """一次 codex 批解析整份清單 → 對齊行序的 list[fields]。I/O 邊界,不單測。

    lines 已是去掉勾選框前綴的『內容』（見 ingest.strip_checkbox）。
    codex_text 走 stdin、可承載超長 batch；回的陣列由 parse_place_list_json 對齊行數。
    """
    n = len(lines)
    if n == 0:
        return []
    blob = "\n".join(lines)
    raw = codex_text(_PLACE_LIST_PROMPT.format(lines=blob))
    return parse_place_list_json(raw, n)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add food/extract.py tests/test_food_batch.py
git commit -m "feat(food): parse_place_list batch codex extract + pure JSON aligner"
```

---

## Task 2: `ingest.strip_checkbox` — 剝勾選框前綴 → (status, content)（純函式 TDD）

**Files:**
- Modify: `food/ingest.py`（檔尾新增 `strip_checkbox`）
- Test: `tests/test_food_batch.py`（追加測試）

> `[x]`（不分大小寫）= 去過；`[ ]` / 無前綴 = 想去。**尾端括號原樣保留**給 codex（含沒收尾的 `(台中`）。

- [ ] **Step 1: 寫失敗測試（追加到 `tests/test_food_batch.py` 檔尾）**

```python
from food.ingest import strip_checkbox


def test_strip_checkbox_unchecked():
    assert strip_checkbox("- [ ] 鼎泰豐 (信義店)") == ("想去", "鼎泰豐 (信義店)")


def test_strip_checkbox_checked_lowercase():
    assert strip_checkbox("- [x] 映客 (台中") == ("去過", "映客 (台中")


def test_strip_checkbox_checked_uppercase():
    assert strip_checkbox("- [X] 海底撈") == ("去過", "海底撈")


def test_strip_checkbox_no_space_variant():
    assert strip_checkbox("-[x]鼎泰豐") == ("去過", "鼎泰豐")
    assert strip_checkbox("-[ ]海底撈") == ("想去", "海底撈")


def test_strip_checkbox_asterisk_bullet():
    assert strip_checkbox("* [ ] 這家拉麵超好吃 (台中)") == ("想去", "這家拉麵超好吃 (台中)")
    assert strip_checkbox("* [x] 火鍋店") == ("去過", "火鍋店")


def test_strip_checkbox_no_prefix_is_wishlist():
    assert strip_checkbox("海底撈") == ("想去", "海底撈")


def test_strip_checkbox_plain_dash_bullet_no_checkbox():
    # 只有 markdown 項目符號、沒有勾選框 → 想去、剝掉項目符號
    assert strip_checkbox("- 鼎泰豐") == ("想去", "鼎泰豐")


def test_strip_checkbox_keeps_trailing_paren_unclosed():
    # 沒收尾的括號原樣保留給 codex
    assert strip_checkbox("- [x] 映客牛蒡天婦羅 (台中") == ("去過", "映客牛蒡天婦羅 (台中")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k strip_checkbox -v`
Expected: FAIL（`ImportError: cannot import name 'strip_checkbox' from 'food.ingest'`）

- [ ] **Step 3: 在 `food/ingest.py` 檔尾新增 `strip_checkbox`**

在 `food/ingest.py` 最上方 import 區之後（檔尾即可）追加。先在檔頭既有 import 區加 `import re`（若尚無）：

`food/ingest.py` 第 9 行 `from food import extract` 之前加一行：

```python
import re
```

然後在 `food/ingest.py` 檔尾追加：

```python
# 勾選框前綴：可選項目符號(- / *) + 中括號狀態框；[x]/[X]=去過、[ ]/空=想去
_CHECKBOX_RE = re.compile(r"^\s*(?:[-*]\s*)?\[\s*([xX ]?)\s*\]\s*")
# 純項目符號(無勾選框)：- 店名 / * 店名
_BULLET_RE = re.compile(r"^\s*[-*]\s+")


def strip_checkbox(line: str) -> tuple[str, str]:
    """剝 markdown 待辦勾選框前綴,帶出狀態（純函式,可單測）。

    回 (status, content)：
      "- [ ] 鼎泰豐 (信義店)" → ("想去", "鼎泰豐 (信義店)")
      "- [x] 映客 (台中"      → ("去過", "映客 (台中")   # 尾端括號原樣保留給 codex
      "- 鼎泰豐"              → ("想去", "鼎泰豐")
      "海底撈"               → ("想去", "海底撈")
    [x]/[X]=去過,其餘=想去。尾端括號不動。
    """
    s = line or ""
    m = _CHECKBOX_RE.match(s)
    if m:
        status = "去過" if m.group(1).lower() == "x" else "想去"
        return status, s[m.end():].strip()
    # 沒勾選框 → 想去；若只是項目符號(- / *)也剝掉
    return "想去", _BULLET_RE.sub("", s).strip()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k strip_checkbox -v`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add food/ingest.py tests/test_food_batch.py
git commit -m "feat(food): strip_checkbox pure parser (status + content)"
```

---

## Task 3: 行數偵測 + 60 行截斷（純函式 TDD）

**Files:**
- Modify: `food/ingest.py`（檔尾新增 `BATCH_LINE_CAP`、`split_lines`、`is_batch`、`take_capped`）
- Test: `tests/test_food_batch.py`（追加測試）

> spec §5：非空行數 ≥2 → 批次；==1 → 單筆。§6.4：上限 60 行，超過只取前 60、回報未處理數（不靜默截斷）。

- [ ] **Step 1: 寫失敗測試（追加到 `tests/test_food_batch.py` 檔尾）**

```python
from food.ingest import split_lines, is_batch, take_capped, BATCH_LINE_CAP


def test_split_lines_drops_blank_and_whitespace():
    text = "鼎泰豐\n\n  \n映客\n   海底撈  "
    assert split_lines(text) == ["鼎泰豐", "映客", "海底撈"]


def test_split_lines_empty():
    assert split_lines("") == []
    assert split_lines("   \n  \n") == []


def test_is_batch_two_or_more_lines():
    assert is_batch("鼎泰豐\n映客") is True
    assert is_batch("鼎泰豐\n\n映客\n海底撈") is True


def test_is_batch_single_line_false():
    assert is_batch("鼎泰豐 信義店") is False
    assert is_batch("鼎泰豐\n\n  \n") is False   # 只有一個非空行
    assert is_batch("") is False


def test_take_capped_under_cap():
    lines = ["a", "b", "c"]
    kept, dropped = take_capped(lines)
    assert kept == ["a", "b", "c"]
    assert dropped == 0


def test_take_capped_over_cap_reports_remainder():
    lines = [f"店{i}" for i in range(70)]
    kept, dropped = take_capped(lines)
    assert len(kept) == BATCH_LINE_CAP == 60
    assert kept[0] == "店0"
    assert kept[-1] == "店59"
    assert dropped == 10
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k "split_lines or is_batch or take_capped" -v`
Expected: FAIL（`ImportError: cannot import name 'split_lines' from 'food.ingest'`）

- [ ] **Step 3: 在 `food/ingest.py` 檔尾新增三個純函式 + 常數**

在 `food/ingest.py` 檔尾（`strip_checkbox` 之後）追加：

```python
BATCH_LINE_CAP = 60  # 單則訊息批次上限；超過只處理前 60 行（spec §6.4）


def split_lines(text: str) -> list[str]:
    """切行、去空白行、每行 strip（純函式）。"""
    if not text:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def is_batch(text: str) -> bool:
    """非空行數 ≥ 2 → 批次（spec §5）。"""
    return len(split_lines(text)) >= 2


def take_capped(lines: list[str]) -> tuple[list[str], int]:
    """取前 BATCH_LINE_CAP 行；回 (kept, dropped)。dropped>0 時總結卡明講未處理數。"""
    kept = lines[:BATCH_LINE_CAP]
    dropped = max(0, len(lines) - BATCH_LINE_CAP)
    return kept, dropped
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k "split_lines or is_batch or take_capped" -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add food/ingest.py tests/test_food_batch.py
git commit -m "feat(food): batch line detect + 60-line cap (pure)"
```

---

## Task 4: 信心分桶 `bucket_line`（純函式 TDD）

**Files:**
- Modify: `food/ingest.py`（檔尾新增 `bucket_line`）
- Test: `tests/test_food_batch.py`（追加測試）

> spec §6.2 桶規則：
> - **✅ 高信心**：codex 抽到 `area` **且** Google 回的店有 `city`（`place["city"]` 非空）。
> - **⚠️ 需確認**：Google 有配對，但 codex **無 area** 或 Google 回的店**無 city**。
> - **❌ 找不到**：codex 抽不到店名（`fields["name"]` 空）或 Google 無配對（`place is None`）。
> `bucket_line(fields, place)` 回 `"ok" | "review" | "fail"`（純函式）。

- [ ] **Step 1: 寫失敗測試（追加到 `tests/test_food_batch.py` 檔尾）**

```python
from food.ingest import bucket_line


def _place(city="台北市"):
    return {"place_id": "p1", "name": "鼎泰豐 信義店", "city": city}


def test_bucket_ok_needs_area_and_city():
    # codex 有 area + Google 有 city → ✅
    fields = {"name": "鼎泰豐", "area": "信義"}
    assert bucket_line(fields, _place(city="台北市")) == "ok"


def test_bucket_review_when_no_area():
    # 有配對但 codex 無 area → ⚠️
    fields = {"name": "鼎泰豐", "area": ""}
    assert bucket_line(fields, _place(city="台北市")) == "review"


def test_bucket_review_when_google_no_city():
    # codex 有 area 但 Google 無 city/country → ⚠️
    fields = {"name": "鼎泰豐", "area": "信義"}
    assert bucket_line(fields, _place(city=None)) == "review"
    assert bucket_line(fields, _place(city="")) == "review"


def test_bucket_ok_overseas_country_only():
    # 國外店：Google 只回 country、無 city,但 codex 有 area → 仍 ✅
    fields = {"name": "一蘭", "area": "福岡"}
    assert bucket_line(fields, {"place_id": "p2", "name": "一蘭 天神店", "city": "", "country": "日本"}) == "ok"


def test_bucket_fail_when_no_name():
    # codex 抽不到店名 → ❌
    fields = {"name": "", "area": ""}
    assert bucket_line(fields, _place()) == "fail"


def test_bucket_fail_when_no_place():
    # Google 無配對 → ❌
    fields = {"name": "鼎泰豐", "area": "信義"}
    assert bucket_line(fields, None) == "fail"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k bucket -v`
Expected: FAIL（`ImportError: cannot import name 'bucket_line' from 'food.ingest'`）

- [ ] **Step 3: 在 `food/ingest.py` 檔尾新增 `bucket_line`**

在 `food/ingest.py` 檔尾（`take_capped` 之後）追加：

```python
def bucket_line(fields: dict, place: dict | None) -> str:
    """信心分桶（純函式,spec §6.2）。回 "ok" | "review" | "fail"。

    ✅ ok    ：codex 有 area 且 Google 回的店有 city 或 country
    ⚠️ review：有配對(place 非 None)但 codex 無 area 或 Google 無 city/country
    ❌ fail   ：codex 抽不到店名,或 Google 無配對(place 為 None)

    用 city 或 country 是為了國外店：country 一定填、city 有就填(spec 美食地圖 §4.1),
    國外只有 country 的店若 codex 也給了 area,仍算高信心。
    """
    name = (fields.get("name") or "").strip()
    if not name or place is None:
        return "fail"
    area = (fields.get("area") or "").strip()
    city = (place.get("city") or "").strip()
    country = (place.get("country") or "").strip()
    if area and (city or country):
        return "ok"
    return "review"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k bucket -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add food/ingest.py tests/test_food_batch.py
git commit -m "feat(food): confidence bucket_line pure logic (ok/review/fail)"
```

---

## Task 5: `dedupe_resolved` — place_id 程序內去重 + 狀態升級（純函式 TDD，修 TOCTOU）

**Files:**
- Modify: `food/ingest.py`（檔尾新增 `dedupe_resolved`）
- Test: `tests/test_food_batch.py`（追加測試）

> spec §6.1：先收集 `resolved`（每筆 `{place, fields, area_given, status, raw}`）→ 依 `place_id` 去重（同店清單出現兩次只 upsert 一次）→ 任一筆為「去過」則該店標去過（**只升級不降級**）。保序：以第一次出現的順序。

- [ ] **Step 1: 寫失敗測試（追加到 `tests/test_food_batch.py` 檔尾）**

```python
from food.ingest import dedupe_resolved


def _r(place_id, status, name="店", raw="raw"):
    return {
        "place": {"place_id": place_id, "name": name, "city": "台北市"},
        "fields": {"name": name, "area": "信義", "recommended_items": "", "cuisine_type": ""},
        "area_given": True,
        "status": status,
        "raw": raw,
    }


def test_dedupe_collapses_same_place_id():
    resolved = [_r("p1", "想去", raw="A"), _r("p1", "想去", raw="B"), _r("p2", "想去")]
    out = dedupe_resolved(resolved)
    ids = [r["place"]["place_id"] for r in out]
    assert ids == ["p1", "p2"]               # 保序、p1 只出現一次


def test_dedupe_status_upgrade_to_visited():
    # 同店一筆想去、一筆去過 → 升級成去過（只升級不降級）
    resolved = [_r("p1", "想去"), _r("p1", "去過")]
    out = dedupe_resolved(resolved)
    assert len(out) == 1
    assert out[0]["status"] == "去過"


def test_dedupe_visited_first_then_wishlist_stays_visited():
    # 先去過後想去 → 仍維持去過（不降級）
    resolved = [_r("p1", "去過"), _r("p1", "想去")]
    out = dedupe_resolved(resolved)
    assert len(out) == 1
    assert out[0]["status"] == "去過"


def test_dedupe_keeps_first_fields():
    # 去重後保留第一次出現那筆的 fields/raw（狀態可被升級覆寫）
    resolved = [_r("p1", "想去", raw="first"), _r("p1", "去過", raw="second")]
    out = dedupe_resolved(resolved)
    assert out[0]["raw"] == "first"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k dedupe -v`
Expected: FAIL（`ImportError: cannot import name 'dedupe_resolved' from 'food.ingest'`）

- [ ] **Step 3: 在 `food/ingest.py` 檔尾新增 `dedupe_resolved`**

在 `food/ingest.py` 檔尾（`bucket_line` 之後）追加：

```python
def dedupe_resolved(resolved: list[dict]) -> list[dict]:
    """依 place_id 程序內去重(保序),狀態只升級不降級（純函式,spec §6.1 修 TOCTOU）。

    resolved 每筆 = {place, fields, area_given, status, raw}。
    同一 place_id 只留第一筆;若任一筆 status=="去過" 則該店升級為去過。
    """
    by_place: dict[str, dict] = {}
    order: list[str] = []
    for r in resolved:
        pid = r["place"]["place_id"]
        cur = by_place.get(pid)
        if cur is None:
            by_place[pid] = dict(r)        # 淺拷貝,避免改到原物件
            order.append(pid)
        elif r["status"] == "去過":
            cur["status"] = "去過"          # 只升級不降級
    return [by_place[pid] for pid in order]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker compose exec -T app pytest tests/test_food_batch.py -k dedupe -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add food/ingest.py tests/test_food_batch.py
git commit -m "feat(food): dedupe_resolved by place_id with status-upgrade (pure)"
```

---

## Task 6: `batch_from_text` orchestrator + `repo.delete_place`（async 串接 + DB 邊界，不單測）

**Files:**
- Modify: `food/ingest.py`（檔頭加 `import asyncio`；檔尾新增同步 `_resolve_one` + async `batch_from_text`）
- Modify: `food/repo.py`（新增 `delete_place`）

> I/O 邊界（codex / Google / DB / asyncio），不寫 pytest（spec §9）。串接已單測的純函式（`split_lines`/`take_capped`/`strip_checkbox`/`parse_place_list`/`bucket_line`/`dedupe_resolved`），以手動驗證確認端到端。
> **Semaphore 只放 async 層**（`async with sem: await asyncio.to_thread(...)`），**不可**放進 `_resolve_one`（sync thread 無法 `async with` asyncio 物件，spec §6.4）。
> **collect-then-dedup-then-upsert**：`_resolve_one` 只做 `search_text`+分桶判定、**不 upsert**；先收齊 `resolved` → `dedupe_resolved` → 才統一 `upsert_place`/`set_visited`（spec §6.1，修 TOCTOU）。

- [ ] **Step 1: 在 `food/repo.py` 新增 `delete_place`**

在 `food/repo.py` 檔尾（`set_visited_by_message_id` 之後）追加：

```python
def delete_place(food_id: int) -> bool:
    """依編號(FoodPlace.id)刪除一家店。刪到回 True、查無回 False。

    回 bool（與 set_visited 的 dict-or-None 不同）：刪除只需成功/失敗布林（spec §7）。
    """
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is None:
            return False
        db.delete(rec)
        db.commit()
        return True
    finally:
        db.close()
```

- [ ] **Step 2: 在 `food/ingest.py` 檔頭加 `import asyncio`**

`food/ingest.py` 既有 `import re` 之後（檔頭 import 區）加一行：

```python
import asyncio
```

並在既有 `from food.repo import upsert_place, update_caution` 那行補上 `set_visited`：

把 `food/ingest.py` 第 12 行：

```python
from food.repo import upsert_place, update_caution
```

改成：

```python
from food.repo import upsert_place, update_caution, set_visited
```

並補 `search_text` 已在第 11 行 import（`from food.places import search_text, caution_for_place_id`），直接複用。

- [ ] **Step 3: 在 `food/ingest.py` 檔尾新增同步 `_resolve_one` + async `batch_from_text`**

在 `food/ingest.py` 檔尾（`dedupe_resolved` 之後）追加：

```python
_BATCH_SEMAPHORE = 6  # 同時在飛的 Google 正名上限（net-new 限流,spec §6.4）


def _resolve_one(fields: dict, status: str, content: str) -> dict:
    """同步,在 thread 內跑：Google 正名 + 分桶判定。**不 upsert**（留到去重後統一寫）。

    回 {bucket, place, fields, status, raw}；bucket ∈ {"ok","review","fail"}。
    name 空 / Google 無配對 / 例外 → bucket="fail"、place=None。
    """
    name = (fields.get("name") or "").strip()
    if not name:
        return {"bucket": "fail", "place": None, "fields": fields,
                "status": status, "raw": content}
    query = f"{name} {fields.get('area') or ''}".strip()
    try:
        place = search_text(query)
    except Exception:
        place = None
    bucket = bucket_line(fields, place)
    return {"bucket": bucket, "place": place, "fields": fields,
            "status": status, "raw": content}


async def batch_from_text(blob: str) -> dict:
    """批次匯入 orchestrator（spec §6）。回 buckets dict 給 food_batch_summary_embed。

    回 {
      "total_lines": int,          # 取前 cap 後實際處理的非空行數
      "dropped": int,              # 超過 60 行未處理數（0=未截斷）
      "wishlist": int, "visited": int,   # 想去/去過計數（標題用）
      "ok": int,                   # ✅ 高信心家數（已入庫,預設只給計數）
      "review": list[dict],        # ⚠️ 需確認：[{id, raw_name, resolved_name}]
      "fail": list[str],           # ❌ 找不到：[原始該行文字]
      "error": str | None,         # 整批 codex 掛掉 → 一句訊息,其餘欄位空
    }
    """
    lines = split_lines(blob)
    kept, dropped = take_capped(lines)
    base = {"total_lines": len(kept), "dropped": dropped, "wishlist": 0,
            "visited": 0, "ok": 0, "review": [], "fail": [], "error": None}
    if not kept:
        return base

    # 0) 行正規化：剝勾選框、帶出狀態
    parsed = [strip_checkbox(ln) for ln in kept]      # list[(status, content)]
    statuses = [s for s, _ in parsed]
    contents = [c for _, c in parsed]
    base["wishlist"] = sum(1 for s in statuses if s == "想去")
    base["visited"] = sum(1 for s in statuses if s == "去過")

    # 1) 一次 codex 批解析（整批掛掉 → 整批回錯,不假裝成功,spec §8）
    try:
        fields_list = await asyncio.to_thread(extract.parse_place_list, contents)
    except Exception as ex:
        base["error"] = f"解析失敗：{ex}"
        return base

    # 2) 逐行 Google 正名（平行 + Semaphore 限流；限流只在 async 層）
    sem = asyncio.Semaphore(_BATCH_SEMAPHORE)

    async def _bounded(i):
        async with sem:
            return await asyncio.to_thread(
                _resolve_one, fields_list[i], statuses[i], contents[i]
            )

    results = await asyncio.gather(
        *[_bounded(i) for i in range(len(contents))], return_exceptions=True
    )

    # 3) 分流：fail 直接落桶；resolved 留待去重後統一 upsert（修 TOCTOU）
    resolved: list[dict] = []
    for content, res in zip(contents, results):
        if isinstance(res, Exception) or res is None:
            base["fail"].append(content)
            continue
        if res["bucket"] == "fail":
            base["fail"].append(res["raw"])
            continue
        # area_given 供分桶；ok/review 都先入庫
        res["area_given"] = bool((res["fields"].get("area") or "").strip())
        resolved.append(res)

    # 3b) 程序內依 place_id 去重 + 狀態升級,再統一入庫
    for r in dedupe_resolved(resolved):
        place = r["place"]
        fields = r["fields"]
        try:
            p, _created = upsert_place(
                place,
                recommended_items=fields.get("recommended_items") or None,
                cuisine_type=fields.get("cuisine_type") or None,
            )
            if r["status"] == "去過":
                set_visited(p["id"])     # 複用既有;只升級成去過
        except Exception:
            base["fail"].append(r["raw"])
            continue
        if r["bucket"] == "ok":
            base["ok"] += 1
        else:
            base["review"].append({
                "id": p["id"],
                "raw_name": fields.get("name") or r["raw"],
                "resolved_name": place.get("name") or "",
            })
    return base
```

- [ ] **Step 4: 重啟並手動驗證端到端（codex + Google + DB 真跑）**

Run: `docker compose restart app`
Run:
```bash
docker compose exec -T app python -c "
import asyncio
from food import ingest
blob = '- [ ] 鼎泰豐 (信義店)\n- [x] 鼎泰豐 信義店\n- [ ] 這家拉麵超好吃随便打的店名xyz'
out = asyncio.run(ingest.batch_from_text(blob))
print('total=', out['total_lines'], 'wishlist=', out['wishlist'], 'visited=', out['visited'])
print('ok=', out['ok'], 'review=', out['review'], 'fail=', out['fail'], 'error=', out['error'])
"
```
Expected：`error=None`；前兩行 Google 對到同一家鼎泰豐（place_id 去重成 1 家、因第二行 `[x]` 而標去過、落 ✅ 或 ⚠️）；亂打的第三行落 `fail`（原文在 list 裡）。確認 `total_lines=3`、`visited>=1`。

- [ ] **Step 5: 清掉測試資料**

Run:
```bash
docker compose exec -T app python -c "from database import SessionLocal; from models import FoodPlace; db=SessionLocal(); n=db.query(FoodPlace).filter(FoodPlace.name.like('%鼎泰豐%')).delete(synchronize_session=False); db.commit(); db.close(); print('cleared', n)"
```
Expected: `cleared <N>`

- [ ] **Step 6: 手動驗證 `repo.delete_place`**

Run:
```bash
docker compose exec -T app python -c "
from food.places import search_text
from food.repo import upsert_place, delete_place
p = search_text('鼎泰豐 信義')
d, _ = upsert_place(p)
print('delete existing:', delete_place(d['id']))   # 應 True
print('delete missing :', delete_place(d['id']))   # 同一 id 再刪應 False
print('delete bogus   :', delete_place(999999))    # 應 False
"
```
Expected：`delete existing: True` / `delete missing : False` / `delete bogus : False`

- [ ] **Step 7: Commit**

```bash
git add food/ingest.py food/repo.py
git commit -m "feat(food): batch_from_text orchestrator + repo.delete_place"
```

---

## Task 7: discord_handler — 批次偵測分支 + 總結卡 + `/美食刪除` + 文件

**Files:**
- Modify: `discord_handler.py`（`food_batch_summary_embed` builder、`_handle_food_message` 純文字分支內插入批次偵測、`/美食刪除` slash 指令）
- Modify: `README.md`、`CODEBASE.md`

> 批次偵測寫在純文字分支內、**單行 `from_text` 判斷之前**（spec §7）。慢操作先 `typing()`。批次只回**一張**總結卡（不洗版）。

- [ ] **Step 1: 新增 `food_batch_summary_embed` builder**

在 `discord_handler.py` 既有 `food_map_embed`（約第 273-278 行）之後、`help_embed` 之前新增：

```python
def food_batch_summary_embed(buckets: dict) -> discord.Embed:
    """批次匯入單張總結卡（spec §6.3）。buckets 來自 ingest.batch_from_text。"""
    if buckets.get("error"):
        return error_embed(buckets["error"])
    total = buckets["total_lines"]
    title = (f"🍜 批次匯入完成（共 {total} 行 · "
             f"想去 {buckets['wishlist']} / 去過 {buckets['visited']}）")
    e = discord.Embed(title=title, color=COLOR_FOOD)
    lines = [f"✅ 高信心 {buckets['ok']} 家（已入庫）"]
    review = buckets.get("review") or []
    if review:
        lines.append(f"⚠️ 需確認 {len(review)} 家（沒地區或 Google 沒給城市，請核對）：")
        for r in review[:15]:
            lines.append(f"　· #{r['id']} {r['raw_name']} → {r['resolved_name']}")
        if len(review) > 15:
            lines.append(f"　…還有 {len(review) - 15} 家")
    fail = buckets.get("fail") or []
    if fail:
        lines.append(f"❌ 找不到 {len(fail)} 家（加上地區再重貼）：")
        for raw in fail[:15]:
            lines.append(f"　· 「{raw}」")
        if len(fail) > 15:
            lines.append(f"　…還有 {len(fail) - 15} 家")
    if buckets.get("dropped"):
        lines.append(f"（超過 {ingest.BATCH_LINE_CAP} 行未處理：{buckets['dropped']} 行，請分批再貼）")
    e.description = "\n".join(lines)[:4000]
    e.set_footer(text="猜錯分店？用 /美食刪除 編號 砍掉，再 /美食新增 帶地區重加")
    return e
```

- [ ] **Step 2: 在 `_handle_food_message` 純文字分支插入批次偵測**

把 `discord_handler.py` 純文字分支（約第 467-480 行）：

```python
        # 純文字 ingest
        if message.content and message.content.strip():
            async with message.channel.typing():
                p, missing = ingest.from_text(message.content.strip())
```

改成（在 `from_text` 之前先判斷批次）：

```python
        # 純文字 ingest
        if message.content and message.content.strip():
            text = message.content.strip()
            # 批次偵測：非空行數 ≥ 2 → 批次匯入（單行維持單筆，spec §5/§7）
            if ingest.is_batch(text):
                async with message.channel.typing():
                    buckets = await ingest.batch_from_text(text)
                await message.channel.send(embed=food_batch_summary_embed(buckets))
                return
            async with message.channel.typing():
                p, missing = ingest.from_text(text)
```

> 注意：原分支後續的 `if p:` / `else:` 區塊保持不變（單行路徑完全相容），只是把單行的 `from_text` 餵的字串從 `message.content.strip()` 改成已抽好的 `text` 變數。

- [ ] **Step 3: 新增 `/美食刪除` slash 指令**

在 `discord_handler.py` `_register_commands()` 內、`cmd_food_visited`（`去過`，約第 673-683 行）之後新增：

```python
        @tree.command(name="美食刪除", description="依編號刪除一家店（修正批次猜錯的分店）")
        @app_commands.describe(編號="店家編號")
        async def cmd_food_delete(ix: discord.Interaction, 編號: int):
            await ix.response.defer()
            from food.repo import delete_place
            ok = delete_place(編號)
            if ok:
                await ix.followup.send(f"🗑️ 已刪除 #{編號}")
            else:
                await ix.followup.send(embed=error_embed(f"找不到編號 {編號}"))
```

- [ ] **Step 4: 重啟並驗證 import / 指令同步**

Run: `docker compose restart app`
Run: `docker compose logs app --tail=8`（確認無 import 錯誤、bot 正常上線）
然後在 Discord 確認 `/美食刪除` 出現在指令選單。

- [ ] **Step 5: 在 Discord 實測批次匯入 + 刪除一輪**

1. 在 `#🍜-美食` 貼多行（含勾選框）：
   ```
   - [ ] 鼎泰豐 (信義店)
   - [x] 映客牛蒡天婦羅 (台中
   - [ ] 這家拉麵超好吃随便打xyz
   ```
   → 應回**一張**總結卡：標題含「共 3 行 · 想去 2 / 去過 1」、✅/⚠️/❌ 分列、footer 提示 `/美食刪除`。
2. 對 ⚠️/✅ 入庫的店記下 `#編號`，`/美食刪除 編號:<編號>` → 應回「🗑️ 已刪除 #編號」。
3. `/美食刪除 編號:999999` → 應回「找不到編號 999999」。
4. 貼**單行** `鼎泰豐 信義店`（1 行）→ 應走既有單筆卡片（驗證單行完全相容、未被批次攔截）。

- [ ] **Step 6: 跑全套食物測試確認綠**

Run: `docker compose exec -T app pytest tests/test_food_batch.py tests/test_food_extract.py tests/test_food_recommend.py tests/test_food_links.py -v`
Expected: PASS（全綠，含本計畫新增的 batch 測試）

- [ ] **Step 7: 更新 README / CODEBASE**

`README.md`：
- 在 Discord slash 指令表新增一列 `/美食刪除 編號` —「依編號刪除一家店（修正批次猜錯的分店）」。
- 在美食模組說明處補一句批次匯入用法：「在 #🍜-美食 貼多行（markdown 待辦清單，`- [ ]`/`- [x]`）→ 一次批次匯入，回 ✅高信心/⚠️需確認/❌找不到 總結卡；`- [x]` 標去過。上限 60 行。」

`CODEBASE.md`：
- File Map 的 `food/ingest.py` 條目補：「+ `batch_from_text`（批次匯入 orchestrator）、`strip_checkbox`/`is_batch`/`take_capped`/`bucket_line`/`dedupe_resolved`（純函式）」。
- `food/extract.py` 條目補：「+ `parse_place_list`（一次 codex 批解析）」。
- `food/repo.py` 條目補：「+ `delete_place`」。
- slash 指令數：**實際數一次** `grep -c '@tree.command' discord_handler.py`（現為 23，CODEBASE.md 舊寫「21」已過時、別照抄），加 `/美食刪除` 後設為該數字 +1，並在指令清單加 `/美食刪除`。

- [ ] **Step 8: Commit**

```bash
git add discord_handler.py README.md CODEBASE.md
git commit -m "feat(food): Discord batch import branch + summary embed + /美食刪除"
```

---

## 完成標準

- [ ] `pytest tests/test_food_batch.py` 全綠（`parse_place_list_json`、`strip_checkbox`、`split_lines`/`is_batch`/`take_capped`、`bucket_line`、`dedupe_resolved`）。
- [ ] `pytest tests/` 全綠（未弄壞既有 food 測試）。
- [ ] 在 `#🍜-美食` 貼 ≥2 行 → 一張總結卡（✅/⚠️/❌ 分桶、想去/去過計數、超 60 行明示未處理數）。
- [ ] 單行純文字仍走既有單筆卡片（完全相容）；含連結/圖片的訊息不進批次（前面分支先攔）。
- [ ] `- [x]` 行入庫標去過；清單內同店（或兩寫法對到同一 place_id）只入庫一次、只升級不降級。
- [ ] `/美食刪除 編號` 刪到回「已刪除 #編號」、查無回「找不到編號 N」。
- [ ] 整批 codex 掛掉 → 回「解析失敗：…」一句，不假裝成功。
- [ ] **未動資料模型**（無新增表/欄位）；批次只 `search_text`+`upsert_place`（+ `[x]` 的 `set_visited`），無雷點摘要。
- [ ] README.md / CODEBASE.md 已同步更新。

> 後續可選（spec §12 開放項目，本計畫不做）：上限行數依實際清單調整；✅ 是否逐筆列店名；分桶訊號強化（輸入名 vs Google 回名相似度）；改用 Google 收藏清單匯入（更準、零猜分店，另開規格）。
