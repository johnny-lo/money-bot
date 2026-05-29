# 美食地圖 Phase 1B（截圖自動抽取 + 頻道分流）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `#美食輸入` 丟截圖或文字 → bot 自動抽出店名/類型/推薦品項 → Google Places 正規化 → 存「想去」並貼卡片(含雷點摘要)；抽不到就貼「需補件」,使用者 reply 一句即可接回；對卡片按 ✅ 就標「去過」。

**Architecture:**
- `food/extract.py`：截圖(Gemini Vision) / 文字(codex) → `{name,area,recommended_items,cuisine_type}` JSON。
- `food/pending.py`：in-memory pending dict（key=bot 卡片訊息 ID），無 TTL，重啟丟失可接受。
- `food/places.py` 擴充：`fetch_reviews(place_id)` + `caution_for_place_id(place_id)`（用 codex 摘低星）。
- `food/ingest.py`：orchestration（extract → places → upsert → 事後雷點 best-effort）。
- `discord_handler.py`：`on_message` 依 channel 分流（`#美食輸入` 走 ingest / reply 補件、`#記帳` 仍走圖片記帳，其他頻道圖片給指引提示帶防洗版）；新增 `on_raw_reaction_add` 處理 ✅。

**Tech Stack:** Python 3.11、discord.py、SQLAlchemy、Gemini Vision（既有 `gemini.gemini_image`）、codex CLI（既有 `codex_cli.codex_text`）、Google Places API (New)（已啟用,Text Search + Place Details/reviews）、pytest。

> 對應 spec：`docs/superpowers/specs/2026-05-23-food-map-module-design.md` §3.1, §6.1, §6.3–6.5, §6.7
> 前置：Plan A 已完成（`FoodPlace`、regions/places/repo/recommend、4 個 slash 指令）。
> 專案慣例：每次 commit 同步更新 `README.md` / `CODEBASE.md`（最末 task 統一處理）。
> **關鍵風險**：Task 7 動到既有 `on_message` —— 必須保留「`DISCORD_RECORD_CHANNEL_ID` 未設則退回舊行為」退路,避免悄悄關掉既有圖片記帳。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `food/pending.py` | 建立 | in-memory pending dict + remember/get/consume/clear（純函式風格） |
| `food/extract.py` | 建立 | image/text → 欄位 JSON；`parse_extracted_json()` 純函式可測 |
| `food/places.py` | 修改 | 新增 `fetch_reviews(place_id)`、`caution_for_place_id(place_id)` |
| `food/repo.py` | 修改 | 新增 `set_message_id()`、`update_caution()`、`set_visited_by_message_id()` |
| `food/ingest.py` | 建立 | orchestrator：from_image / from_text → (place_dict_or_None, missing_reason) |
| `discord_handler.py` | 修改 | `on_message` 分流 + reply 補件 + 提示防洗版；`on_raw_reaction_add` ✅；新增 `food_missing_embed` |
| `tests/test_food_pending.py` | 建立 | pending 單測 |
| `tests/test_food_extract.py` | 建立 | `parse_extracted_json` 單測 |

測試：`docker compose exec -T app pytest tests/ -v`
套用：`docker compose restart app`

---

## Task 1: `food/pending.py` 需補件記憶體

**Files:**
- Create: `food/pending.py`
- Test: `tests/test_food_pending.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_food_pending.py`**

```python
import food.pending as pending


def setup_function(_):
    pending.clear()


def test_remember_and_get():
    pending.remember("msg1", original_message_id="orig1", raw_text="hi",
                     missing_reason="no name")
    p = pending.get("msg1")
    assert p["bot_message_id"] == "msg1"
    assert p["original_message_id"] == "orig1"
    assert p["raw_text"] == "hi"
    assert p["missing_reason"] == "no name"


def test_consume_removes():
    pending.remember("msg2", original_message_id="o2")
    assert pending.consume("msg2") is not None
    assert pending.get("msg2") is None


def test_missing_returns_none():
    assert pending.get("nope") is None
    assert pending.consume("nope") is None


def test_int_and_str_keys_normalized():
    pending.remember(123, original_message_id=456)
    assert pending.get("123") is not None
    assert pending.consume(123) is not None
```

- [ ] **Step 2: 跑測試確認失敗**

`docker compose exec -T app pytest tests/test_food_pending.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: 實作 `food/pending.py`**

```python
"""需補件 in-memory 暫存（無 TTL；bot 重啟丟失可接受）。"""
import time

_pending: dict[str, dict] = {}


def remember(bot_message_id, *, original_message_id, raw_text: str = "",
             source_url: str | None = None, attachment_url: str | None = None,
             missing_reason: str = "") -> None:
    """記下一張需補件卡片的上下文。"""
    key = str(bot_message_id)
    _pending[key] = {
        "bot_message_id": key,
        "original_message_id": str(original_message_id),
        "raw_text": raw_text,
        "source_url": source_url,
        "attachment_url": attachment_url,
        "missing_reason": missing_reason,
        "created_at": time.time(),
    }


def get(bot_message_id) -> dict | None:
    return _pending.get(str(bot_message_id))


def consume(bot_message_id) -> dict | None:
    """取出並移除一筆 pending（無就回 None）。"""
    return _pending.pop(str(bot_message_id), None)


def clear() -> None:
    """測試用：清空全部。"""
    _pending.clear()
```

- [ ] **Step 4: 跑測試確認通過**

`docker compose exec -T app pytest tests/test_food_pending.py -v` → 4 passed.

- [ ] **Step 5: Commit**

```bash
git add food/pending.py tests/test_food_pending.py
git commit -m "feat(food): in-memory pending registry for missing-info cards"
```

---

## Task 2: `food/extract.py` 抽取欄位

**Files:**
- Create: `food/extract.py`
- Test: `tests/test_food_extract.py`

> 純函式 `parse_extracted_json()` 做 TDD；`from_image` / `from_text` 是 I/O wrapper（叫 Gemini/codex），不單測。

- [ ] **Step 1: 寫失敗測試 `tests/test_food_extract.py`**

```python
from food.extract import parse_extracted_json


def test_parse_plain_json():
    raw = '{"name":"鼎泰豐","area":"信義","recommended_items":"小籠包","cuisine_type":"中式"}'
    out = parse_extracted_json(raw)
    assert out == {"name": "鼎泰豐", "area": "信義",
                   "recommended_items": "小籠包", "cuisine_type": "中式"}


def test_parse_with_markdown_fences():
    raw = "```json\n{\"name\":\"A\",\"area\":\"\",\"recommended_items\":\"\",\"cuisine_type\":\"\"}\n```"
    out = parse_extracted_json(raw)
    assert out["name"] == "A"
    assert out["area"] == ""


def test_parse_missing_fields_defaults_empty():
    raw = '{"name":"B"}'
    out = parse_extracted_json(raw)
    assert out == {"name": "B", "area": "", "recommended_items": "", "cuisine_type": ""}


def test_parse_whitespace_stripped():
    raw = '   {"name":"  C  ","area":" 台北 "}  '
    out = parse_extracted_json(raw)
    assert out["name"] == "C"
    assert out["area"] == "台北"
```

- [ ] **Step 2: 跑測試確認失敗**

`docker compose exec -T app pytest tests/test_food_extract.py -v`

- [ ] **Step 3: 實作 `food/extract.py`**

```python
"""影片/文字/截圖 → 店家欄位 JSON。

- parse_extracted_json：純函式，把 AI 回應字串解析成 {name, area, recommended_items, cuisine_type}
- from_text：用 codex_text 把純文字抽成欄位
- from_image：用 gemini_image 直接從截圖一步到位抽欄位
"""
import json

from gemini import gemini_image
from codex_cli import codex_text


_TEXT_PROMPT = (
    "請從以下文字內容中擷取店家資訊，只回 JSON、不要 markdown 標籤：\n"
    '{{"name":"店名(沒有就空字串)","area":"區域提示(縣市/城市)","'
    'recommended_items":"推薦品項(可空)","cuisine_type":"料理類型(可空)"}}\n\n'
    "文字內容：\n{text}"
)

_IMAGE_PROMPT = (
    "請從這張圖片擷取店家資訊，只回 JSON、不要 markdown 標籤：\n"
    '{"name":"店名(沒有就空字串)","area":"區域提示(縣市/城市)","'
    'recommended_items":"推薦品項(可空)","cuisine_type":"料理類型(可空)"}'
)


def parse_extracted_json(raw: str) -> dict:
    """把 AI 回應字串清成乾淨 dict。缺欄位以空字串補齊、首尾空白皆 strip。"""
    t = raw.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    d = json.loads(t.strip())
    return {
        "name": (d.get("name") or "").strip(),
        "area": (d.get("area") or "").strip(),
        "recommended_items": (d.get("recommended_items") or "").strip(),
        "cuisine_type": (d.get("cuisine_type") or "").strip(),
    }


def from_text(text: str) -> dict:
    """純文字 → 欄位（codex）。"""
    return parse_extracted_json(codex_text(_TEXT_PROMPT.format(text=text)))


def from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """截圖 → 欄位（Gemini Vision 一次到位）。"""
    return parse_extracted_json(gemini_image(_IMAGE_PROMPT, image_bytes, mime_type=mime_type))
```

- [ ] **Step 4: 跑測試確認通過**

`docker compose exec -T app pytest tests/test_food_extract.py -v` → 4 passed.

- [ ] **Step 5: Commit**

```bash
git add food/extract.py tests/test_food_extract.py
git commit -m "feat(food): extract fields from text/image"
```

---

## Task 3: `food/places.py` 擴充——雷點摘要

**Files:**
- Modify: `food/places.py`（追加兩個函式）

> 接 Place Details / reviews 是真實 I/O；以手動驗證確認，沒有單測。

- [ ] **Step 1: 在 `food/places.py` 末尾追加**

```python
_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"


def fetch_reviews(place_id: str) -> list[dict]:
    """抓 Place Details 的 reviews 欄位（最相關約 5 則）。失敗回 []。"""
    key = os.getenv("GOOGLE_PLACES_SERVER_KEY")
    if not key or not place_id:
        return []
    try:
        req = urllib.request.Request(
            _DETAILS_URL.format(place_id=place_id),
            method="GET",
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "reviews",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return data.get("reviews") or []
    except Exception:
        return []


def caution_for_place_id(place_id: str) -> str:
    """用低星評論做雷點摘要。沒低星回友善訊息；任何失敗回空字串。"""
    from codex_cli import codex_text
    reviews = fetch_reviews(place_id)
    if not reviews:
        return ""
    low_lines: list[str] = []
    for r in reviews:
        rating = r.get("rating") or 0
        text = (r.get("text") or {}).get("text") or r.get("originalText", {}).get("text") or ""
        if rating and rating <= 3 and text:
            low_lines.append(f"({rating}星) {text}")
    if not low_lines:
        return "近期評論沒看到明顯雷點"
    prompt = (
        "以下是 Google 評論的低星留言，請用一句話(<=40字)歸納主要雷點，"
        "台灣口語、不加標題、不列點，直接給文字：\n\n"
        + "\n\n".join(low_lines[:5])
    )
    try:
        return codex_text(prompt).strip()[:200]
    except Exception:
        return ""
```

- [ ] **Step 2: 重啟並手動驗證**

```bash
docker compose restart app
docker compose exec -T app python -c "
from food.places import search_text, caution_for_place_id
p = search_text('鼎泰豐 信義')
print('place_id:', p['place_id'])
print('caution :', caution_for_place_id(p['place_id']) or '(空)')
"
```
Expected：印出非空 place_id；雷點摘要為一句中文（或「近期評論沒看到明顯雷點」）。任一段失敗回空字串均可接受（best-effort）。

- [ ] **Step 3: Commit**

```bash
git add food/places.py
git commit -m "feat(food): Place Details reviews → AI caution summary"
```

---

## Task 4: `food/repo.py` 擴充——message_id / caution / 反向查找

**Files:**
- Modify: `food/repo.py`（追加三個函式）

- [ ] **Step 1: 在 `food/repo.py` 末尾追加**

```python
def set_message_id(food_id: int, message_id) -> None:
    """記下這筆 FoodPlace 對應的 Discord 卡片訊息 ID（給 ✅ 反應回查用）。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is not None:
            rec.discord_message_id = str(message_id)
            db.commit()
    finally:
        db.close()


def update_caution(food_id: int, caution: str) -> None:
    """事後加值雷點摘要。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is not None:
            rec.caution_summary = caution
            db.commit()
    finally:
        db.close()


def set_visited_by_message_id(message_id) -> dict | None:
    """從 Discord 卡片訊息 ID 反查 FoodPlace，標為去過。查無回 None。"""
    db = SessionLocal()
    try:
        rec = (
            db.query(FoodPlace)
            .filter(FoodPlace.discord_message_id == str(message_id))
            .first()
        )
        if rec is None:
            return None
        rec.status = "去過"
        db.commit()
        db.refresh(rec)
        return to_dict(rec)
    finally:
        db.close()
```

- [ ] **Step 2: 重啟並手動驗證**

```bash
docker compose restart app
docker compose exec -T app python -c "
from food.places import search_text
from food.repo import upsert_place, set_message_id, update_caution, set_visited_by_message_id
p = search_text('鼎泰豐 信義')
d, _ = upsert_place(p)
set_message_id(d['id'], 'fake-msg-999')
update_caution(d['id'], '雷點：等很久')
v = set_visited_by_message_id('fake-msg-999')
print('found by msg:', v is not None and v['status'] == '去過' and v['caution_summary'] == '雷點：等很久')
miss = set_visited_by_message_id('not-exist')
print('miss returns None:', miss is None)
"
```
Expected：`found by msg: True` 與 `miss returns None: True`。

- [ ] **Step 3: 清掉測試資料**

```bash
docker compose exec -T app python -c "from database import SessionLocal; from models import FoodPlace; db=SessionLocal(); db.query(FoodPlace).delete(); db.commit(); db.close(); print('cleared')"
```

- [ ] **Step 4: Commit**

```bash
git add food/repo.py
git commit -m "feat(food): repo helpers for discord_message_id + caution"
```

---

## Task 5: `food/ingest.py` 流程整合

**Files:**
- Create: `food/ingest.py`

> 串接 extract → places → upsert → (best-effort) caution。供 `on_message` 呼叫。

- [ ] **Step 1: 實作 `food/ingest.py`**

```python
"""美食抽取 → Places → 入庫 → 事後雷點 的 orchestrator。

回傳 (place_dict_or_None, missing_reason)：
- place_dict_or_None 非 None 代表入庫成功，含 _created（True=新增 / False=更新既有）
- place_dict_or_None None 代表缺資訊或查不到，呼叫端應建 pending 卡

雷點摘要採事後加值（best-effort），失敗不影響入庫。
"""
from food import extract
from food.places import search_text, caution_for_place_id
from food.repo import upsert_place, update_caution


def from_image(image_bytes: bytes, mime_type: str = "image/jpeg",
               *, source_url: str | None = None) -> tuple[dict | None, str]:
    try:
        fields = extract.from_image(image_bytes, mime_type=mime_type)
    except Exception as ex:
        return None, f"截圖辨識失敗：{ex}"
    return _from_fields(fields, source_url=source_url)


def from_text(text: str, *, source_url: str | None = None) -> tuple[dict | None, str]:
    if not text or not text.strip():
        return None, "沒有可解析的文字"
    try:
        fields = extract.from_text(text.strip())
    except Exception as ex:
        return None, f"文字解析失敗：{ex}"
    return _from_fields(fields, source_url=source_url)


def _from_fields(fields: dict, *, source_url: str | None) -> tuple[dict | None, str]:
    name = (fields.get("name") or "").strip()
    if not name:
        return None, "抽不到店名"
    query = f"{name} {fields.get('area') or ''}".strip()
    try:
        place = search_text(query)
    except Exception as ex:
        return None, f"查 Google 失敗：{ex}"
    if not place:
        return None, f"Google 找不到「{query}」"
    p, created = upsert_place(
        place,
        recommended_items=fields.get("recommended_items") or None,
        cuisine_type=fields.get("cuisine_type") or None,
        source_url=source_url,
    )
    # 事後加值：雷點摘要 best-effort
    try:
        c = caution_for_place_id(place["place_id"])
        if c:
            update_caution(p["id"], c)
            p["caution_summary"] = c
    except Exception:
        pass
    p["_created"] = created
    return p, ""
```

- [ ] **Step 2: 重啟並手動驗證 text 路徑（image 路徑要透過 Discord 才能完整測，這裡先驗 text + 雷點）**

```bash
docker compose restart app
docker compose exec -T app python -c "
from food.ingest import from_text
p, missing = from_text('鼎泰豐 信義 推薦小籠包')
print('p:', None if p is None else (p['name'], p['city'], p['_created']))
print('caution:', None if p is None else (p.get('caution_summary') or '(空)'))
print('missing:', missing or '(無)')
"
```
Expected：`p` 非 None、name 含「鼎泰豐」、city='台北市'、`_created=True`（或 False 若重複跑）；雷點摘要為一句中文或「(空)」（best-effort）。

- [ ] **Step 3: 清掉測試資料**

```bash
docker compose exec -T app python -c "from database import SessionLocal; from models import FoodPlace; db=SessionLocal(); db.query(FoodPlace).delete(); db.commit(); db.close(); print('cleared')"
```

- [ ] **Step 4: Commit**

```bash
git add food/ingest.py
git commit -m "feat(food): ingest orchestrator (extract → places → upsert → caution)"
```

---

## Task 6: `food_missing_embed`（需補件卡片）

**Files:**
- Modify: `discord_handler.py`（在 `food_reco_embed` 旁追加一個 embed builder）

- [ ] **Step 1: 在 `discord_handler.py` 中追加（接在 `food_reco_embed` 後）**

```python
def food_missing_embed(reason: str, *, hint: str = "") -> discord.Embed:
    """需補件卡片：用 reply 回覆本卡片補上店名/地址即可接回。"""
    e = discord.Embed(
        title="⚠️ 抽不到完整資訊，請補件",
        description=reason or "缺少店名",
        color=COLOR_WARN,
    )
    if hint:
        e.add_field(name="提示", value=hint, inline=False)
    e.set_footer(text="🔁 直接 reply 這張卡片，補上店名或更完整的店名+區域")
    return e
```

- [ ] **Step 2: 重啟並 smoke test**

```bash
docker compose restart app
docker compose exec -T app python -c "
import discord_handler as dh
e = dh.food_missing_embed('Google 找不到「某店 台北」')
print(type(e).__name__, e.title, '|', e.description, '|', e.footer.text)
"
```
Expected：印出 `Embed ⚠️ 抽不到完整資訊，請補件 | Google 找不到「某店 台北」 | 🔁 直接 reply ...`

- [ ] **Step 3: Commit**

```bash
git add discord_handler.py
git commit -m "feat(food): missing-info embed for human-in-the-loop补件"
```

---

## Task 7: `on_message` 頻道分流（最大整合風險）

**Files:**
- Modify: `discord_handler.py`（改寫 `on_message` 方法 + 加 hint 防洗版小工具）

> **核心防撞**：必須保留「`DISCORD_RECORD_CHANNEL_ID` 未設則退回舊行為」退路，並對其他頻道圖片只給指引、不靜默。

- [ ] **Step 1: 在 `discord_handler.py` 模組頂端（其他模組級常數附近）加 hint debounce 結構**

```python
# 非目標頻道圖片提示的防洗版：{channel_id: last_hint_ts}
_HINT_DEBOUNCE: dict[int, float] = {}
HINT_COOLDOWN_SEC = 1800  # 30 分鐘
```

- [ ] **Step 2: 改寫 `MoneyBot.on_message` 為下列完整版本**

> 找出 `class MoneyBot(...)` 內既有的 `async def on_message(self, message: discord.Message):` 整個函式，**整段** 換成下面的版本（保留縮排）：

```python
    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return

        food_chan = os.getenv("FOOD_INGEST_CHANNEL_ID") or ""
        rec_chan = os.getenv("DISCORD_RECORD_CHANNEL_ID") or ""
        ch_id = str(message.channel.id)

        # ── 1) 美食頻道：reply 補件 / 圖片或文字 ingest ─────────────
        if food_chan and ch_id == food_chan:
            await self._handle_food_message(message)
            return

        # ── 2) 圖片附件分流 ───────────────────────────────────────
        if message.attachments:
            # 過濾出圖片附件
            images = [a for a in message.attachments
                      if a.content_type and a.content_type.startswith("image/")]
            if not images:
                return
            if not rec_chan:
                # 退路：未設記帳頻道 → 保留舊的「任意頻道圖片記帳」行為
                await self._do_image_recording(message, images[0])
                return
            if ch_id == rec_chan:
                await self._do_image_recording(message, images[0])
                return
            # 其他頻道：提示分流（含防洗版）
            import time as _time
            now = _time.time()
            last = _HINT_DEBOUNCE.get(message.channel.id, 0)
            if now - last >= HINT_COOLDOWN_SEC:
                _HINT_DEBOUNCE[message.channel.id] = now
                await message.channel.send(
                    "💡 記帳請丟 <#" + rec_chan + ">，記美食請丟 <#" + (food_chan or "") + ">"
                )
            return
        # 非圖片、非美食頻道訊息 → 不處理（讓 slash 自行運作）

    async def _do_image_recording(self, message: discord.Message, att: discord.Attachment):
        async with message.channel.typing():
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(att.url) as resp:
                        image_bytes = await resp.read()
                data = handle_image_data(image_bytes)
                embeds = [image_recorded_embed(data)]
                pe = persona_embed(data.get("persona", ""))
                if pe:
                    embeds.append(pe)
                await message.channel.send(embeds=embeds)
            except Exception as e:
                await message.channel.send(embed=error_embed(f"視覺大腦失敗：{e}"))

    async def _handle_food_message(self, message: discord.Message):
        from food import ingest, pending
        from food.repo import set_message_id

        # reply 補件：上一張 ⚠️ 卡片的補件回覆
        ref = getattr(message, "reference", None)
        if ref and ref.message_id and pending.get(ref.message_id):
            ctx = pending.consume(ref.message_id)
            async with message.channel.typing():
                merged = (ctx.get("raw_text") or "") + " " + (message.content or "")
                p, missing = ingest.from_text(merged.strip(),
                                              source_url=ctx.get("source_url"))
            if p:
                sent = await message.channel.send(
                    embed=food_place_embed(p, created=p.get("_created", True))
                )
                set_message_id(p["id"], sent.id)
            else:
                sent = await message.channel.send(embed=food_missing_embed(missing))
                pending.remember(sent.id, original_message_id=message.id,
                                 raw_text=merged.strip(),
                                 source_url=ctx.get("source_url"),
                                 missing_reason=missing)
            return

        # 圖片 ingest
        images = [a for a in message.attachments
                  if a.content_type and a.content_type.startswith("image/")]
        if images:
            att = images[0]
            async with message.channel.typing():
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(att.url) as resp:
                            image_bytes = await resp.read()
                    p, missing = ingest.from_image(
                        image_bytes,
                        mime_type=att.content_type or "image/jpeg",
                        source_url=att.url,
                    )
                except Exception as ex:
                    await message.channel.send(embed=error_embed(f"處理截圖失敗：{ex}"))
                    return
            if p:
                sent = await message.channel.send(
                    embed=food_place_embed(p, created=p.get("_created", True))
                )
                set_message_id(p["id"], sent.id)
            else:
                sent = await message.channel.send(embed=food_missing_embed(missing))
                pending.remember(sent.id, original_message_id=message.id,
                                 attachment_url=att.url,
                                 missing_reason=missing)
            return

        # 純文字 ingest
        if message.content and message.content.strip():
            async with message.channel.typing():
                p, missing = ingest.from_text(message.content.strip())
            if p:
                sent = await message.channel.send(
                    embed=food_place_embed(p, created=p.get("_created", True))
                )
                set_message_id(p["id"], sent.id)
            else:
                sent = await message.channel.send(embed=food_missing_embed(missing))
                pending.remember(sent.id, original_message_id=message.id,
                                 raw_text=message.content.strip(),
                                 missing_reason=missing)
```

- [ ] **Step 3: 重啟並驗證**

```bash
docker compose restart app
docker compose logs app --tail=10
docker compose exec -T app python -c "
import discord_handler as dh
print('on_message ok:', hasattr(dh.MoneyBot, 'on_message'))
print('food handler ok:', hasattr(dh.MoneyBot, '_handle_food_message'))
print('rec handler ok :', hasattr(dh.MoneyBot, '_do_image_recording'))
print('HINT_COOLDOWN_SEC=', dh.HINT_COOLDOWN_SEC)
"
```
Expected：log 無 traceback、bot 連上線；三個 hasattr 都 True；常數印出 1800。
（真正 UI 行為留待 Task 9 後人工 Discord 測試。）

- [ ] **Step 4: 跑全測試確認無回歸**

`docker compose exec -T app pytest tests/ -q`
Expected：仍全綠（69 = 之前 61 + Task 1 的 4 + Task 2 的 4）。

> 若全測試數字對不上，先檢查 Task 1/2 commit 是否漏掉。

- [ ] **Step 5: Commit**

```bash
git add discord_handler.py
git commit -m "feat(food): on_message channel routing + food ingest + pending reply"
```

---

## Task 8: `on_raw_reaction_add` ✅ 反應標去過

**Files:**
- Modify: `discord_handler.py`（在 `MoneyBot` 內 `on_message` 後追加方法）

- [ ] **Step 1: 在 `MoneyBot` 類別內追加方法**

```python
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # 自己的反應不處理
        if payload.user_id == (self.user.id if self.user else 0):
            return
        food_chan = os.getenv("FOOD_INGEST_CHANNEL_ID") or ""
        if not food_chan or str(payload.channel_id) != food_chan:
            return
        if str(payload.emoji) != "✅":
            return
        from food.repo import set_visited_by_message_id
        rec = set_visited_by_message_id(payload.message_id)
        if rec is None:
            return
        ch = self.get_channel(payload.channel_id)
        if ch:
            await ch.send(
                f"🍜 已標記去過：**{rec['name']}**（編號 {rec['id']}）。"
                "想記評分/心得嗎？回我一句或用 `/去過`。"
            )
```

- [ ] **Step 2: 重啟並驗證**

```bash
docker compose restart app
docker compose logs app --tail=10
docker compose exec -T app python -c "
from discord_handler import MoneyBot
print('reaction ok:', hasattr(MoneyBot, 'on_raw_reaction_add'))
"
```
Expected：`reaction ok: True`、log 無 traceback。

- [ ] **Step 3: Commit**

```bash
git add discord_handler.py
git commit -m "feat(food): ✅ reaction → mark visited + follow-up prompt"
```

---

## Task 9: 文件 + 最終 commit

**Files:**
- Modify: `README.md`、`CODEBASE.md`

- [ ] **Step 1: 更新 `README.md`**

在「Discord」slash 表後新增一節（或調整既有內容）說明 **#美食輸入**：
- 在 `#美食輸入` 丟**截圖**或**文字**（如「鼎泰豐 信義」）→ bot 自動抽店名、查 Google、入庫並貼卡片（含雷點摘要 best-effort）
- 抽不到完整資訊 → 貼 ⚠️ 需補件卡片，**reply 該卡片**補上店名/地址即可
- 對店家卡片按 ✅ → 立刻標「去過」（之後再用 `/去過` 補評分/心得）
- 其他頻道誤丟圖片：bot 會回一句指引（同頻道 30 分鐘內只回一次）

順手把「自動報表」段落底下加一段「美食地圖」說明（如已存在 Phase 1A 區塊就補上 Phase 1B 內容）。

- [ ] **Step 2: 更新 `CODEBASE.md`**

- File Map 的 `food/` 加 `extract.py`、`pending.py`、`ingest.py`
- `discord_handler.py` 條目補：「`on_message` 依頻道分流（`FOOD_INGEST_CHANNEL_ID` 走美食 ingest、`DISCORD_RECORD_CHANNEL_ID` 走圖片記帳；未設記帳頻道則退回舊行為；其他頻道圖片回指引含 30 分鐘防洗版）；`on_raw_reaction_add` ✅ 標去過。」
- 「規劃中模組」的美食地圖條目：把 Phase 1B 從規劃改為「已實作（截圖自動 ingest + reply 補件 + ✅ + 雷點摘要）」

- [ ] **Step 3: Commit**

```bash
git add README.md CODEBASE.md
git commit -m "docs(food): Phase 1B auto-capture flow + on_message routing"
```

---

## 完成標準（Plan B）

- [ ] `pytest tests/` 全綠（≥ 69：原 61 + Task 1 的 4 + Task 2 的 4）
- [ ] `docker compose logs app` 啟動後無 traceback、bot 上線
- [ ] **Discord 真人實測（合併前必做）**：
  1. 在 `#美食輸入` 丟一張含店名的截圖 → 自動回卡片（含雷點若有）
  2. 在 `#美食輸入` 打 `麥當勞 信義` → 自動回卡片
  3. 故意丟一段抽不到店名的文字 → ⚠️ 卡片;reply「鼎泰豐 信義」→ 自動接回正式卡片
  4. 對某張卡片按 ✅ → bot 回「已標記去過 …」
  5. 在 `#記帳` 丟發票圖 → 仍走原本圖片記帳（未動）
  6. 在其他頻道丟圖 → 回一次指引,連續再丟不再回（防洗版）

通過後進 `superpowers:finishing-a-development-branch` 收尾。
