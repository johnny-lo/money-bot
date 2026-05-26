# 美食地圖 Phase 1A（純 slash 地基）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 4 個 Discord slash 指令建立可用的「私人美食清單 + 縣市/國家推薦」，完全不更動現有 `on_message`／記帳邏輯。

**Architecture:** 新增 `food/` 套件（純函式 `regions`/`recommend` + I/O 薄封裝 `places`/`repo`）與 `FoodPlace` ORM；`discord_handler.py` 加 4 個 slash 指令與 embed builder。店名靠 Google Places API (New) Text Search 正規化成地址/座標/place_id/國家/縣市，存 DB；推薦純查 DB。

**Tech Stack:** Python 3.11、SQLAlchemy、Google Places API (New)（已於 Phase 0 啟用，key=`GOOGLE_PLACES_SERVER_KEY`）、discord.py、pytest。

> 對應 spec：`docs/superpowers/specs/2026-05-23-food-map-module-design.md`
> 本計畫**不含**：截圖/連結自動抽取、頻道分流、pending 補件、✅ 反應、雷點摘要 → 全在 Plan B。
> 專案慣例：每次 commit 同步更新 `README.md` / `CODEBASE.md`（見 Task 6）。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `models.py` | 修改 | 新增 `FoodPlace` ORM（需 `import Float`） |
| `food/__init__.py` | 建立 | 空，標記套件 |
| `food/regions.py` | 建立 | 地名正規化 `canon()`、比對 `region_matches()`、`parse_address_components()`（純函式） |
| `food/places.py` | 建立 | Google Places (New) Text Search 薄封裝 `search_text()` + `maps_url()` |
| `food/repo.py` | 建立 | `FoodPlace` 的 DB 存取：`upsert_place()`、`list_places()`、`set_visited()`、`to_dict()` |
| `food/recommend.py` | 建立 | `filter_for_recommendation()`、`sort_recent()`、`pick_random()`（純函式） |
| `discord_handler.py` | 修改 | `COLOR_FOOD`、`food_place_embed()`/`food_list_embed()`/`food_reco_embed()`、4 個 slash 指令 |
| `tests/test_food_regions.py` | 建立 | regions 單元測試 |
| `tests/test_food_recommend.py` | 建立 | recommend 單元測試 |

測試執行：`docker compose exec app pytest tests/ -v`
套用程式變更：`docker compose restart app`（純 .py 改動，bind mount + 主進程重啟即重新 import）

---

## Task 1: FoodPlace ORM

**Files:**
- Modify: `models.py:1`（import）、`models.py` 結尾（新增 class）

- [ ] **Step 1: 擴充 import（加 `Float`）**

`models.py` 第 1 行改成：

```python
from sqlalchemy import Column, Integer, String, DateTime, Float, func
```

- [ ] **Step 2: 在 `models.py` 結尾新增 `FoodPlace`**

```python
class FoodPlace(Base):
    """美食地圖：想去/去過的店家"""
    __tablename__ = "food_places"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)                       # 正式店名（Places 正名）
    address = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    place_id = Column(String, unique=True, index=True)      # Google Place 唯一 ID（去重）
    country = Column(String, index=True, nullable=True)
    city = Column(String, index=True, nullable=True)        # 台灣=縣市，國外=城市，可空
    district = Column(String, nullable=True)
    cuisine_type = Column(String, nullable=True, index=True)
    recommended_items = Column(String, nullable=True)
    caution_summary = Column(String, nullable=True)         # 雷點摘要（Plan B 才填）
    status = Column(String, default="想去", index=True)      # 想去 / 去過
    my_rating = Column(Integer, nullable=True)              # 共用評分 1-5
    my_note = Column(String, nullable=True)                # 共用心得
    source_url = Column(String, nullable=True)
    discord_message_id = Column(String, nullable=True, index=True)  # Plan B 的 ✅ 反應用
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

- [ ] **Step 3: 重啟讓 `create_all` 建表**

Run: `docker compose restart app`
（`main.py` 啟動時 `Base.metadata.create_all(bind=engine)` 會自動建 `food_places` 表）

- [ ] **Step 4: 驗證表存在**

Run:
```bash
docker compose exec -T app python -c "from models import FoodPlace; from database import SessionLocal; db=SessionLocal(); print('count =', db.query(FoodPlace).count()); db.close()"
```
Expected: `count = 0`（表存在、可查、目前空）

- [ ] **Step 5: Commit**

```bash
git add models.py
git commit -m "feat(food): add FoodPlace model"
```

---

## Task 2: food/regions.py（地名正規化，純函式 TDD）

**Files:**
- Create: `food/__init__.py`（空）
- Create: `food/regions.py`
- Test: `tests/test_food_regions.py`

- [ ] **Step 1: 建立空套件檔**

```bash
mkdir -p food && : > food/__init__.py
```

- [ ] **Step 2: 寫失敗測試 `tests/test_food_regions.py`**

```python
from food.regions import canon, region_matches, parse_address_components


def test_canon_taiwan_city_aliases():
    assert canon("台中") == "台中市"
    assert canon("台中市") == "台中市"
    assert canon("臺中市") == "台中市"
    assert canon("Taichung City") == "台中市"


def test_canon_country_and_foreign_city():
    assert canon("日本") == "日本"
    assert canon("Japan") == "日本"
    assert canon("東京都") == "東京"
    assert canon("Osaka") == "大阪"


def test_canon_empty():
    assert canon(None) == ""
    assert canon("") == ""


def test_region_matches_taiwan_city():
    assert region_matches("台中", country="台灣", city="台中市") is True
    assert region_matches("台北", country="台灣", city="台中市") is False


def test_region_matches_country_and_foreign_city():
    assert region_matches("日本", country="日本", city="東京") is True
    assert region_matches("大阪", country="日本", city="大阪") is True
    assert region_matches("首爾", country="日本", city="大阪") is False


def test_parse_address_components_taiwan():
    comps = [
        {"longText": "台灣", "types": ["country"]},
        {"longText": "臺中市", "types": ["administrative_area_level_1"]},
        {"longText": "西區", "types": ["administrative_area_level_3"]},
    ]
    out = parse_address_components(comps)
    assert out["country"] == "台灣"
    assert out["city"] == "台中市"
    assert out["district"] == "西區"


def test_parse_address_components_prefers_locality():
    comps = [
        {"longText": "Japan", "types": ["country"]},
        {"longText": "Tokyo", "types": ["locality"]},
        {"longText": "Kanto", "types": ["administrative_area_level_1"]},
    ]
    out = parse_address_components(comps)
    assert out["country"] == "日本"
    assert out["city"] == "東京"
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `docker compose exec -T app pytest tests/test_food_regions.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'food.regions'`）

- [ ] **Step 4: 實作 `food/regions.py`**

```python
"""地名正規化與比對（純函式，無 I/O）。"""

# 別名 → 正規顯示名（key 一律小寫比對）
_CITY_ALIAS = {
    "taichung": "台中市", "台中": "台中市", "臺中": "台中市", "台中市": "台中市", "臺中市": "台中市",
    "taipei": "台北市", "台北": "台北市", "臺北": "台北市", "台北市": "台北市", "臺北市": "台北市",
    "kaohsiung": "高雄市", "高雄": "高雄市", "高雄市": "高雄市",
    "tainan": "台南市", "台南": "台南市", "臺南": "台南市", "台南市": "台南市",
    "tokyo": "東京", "東京": "東京", "東京都": "東京",
    "osaka": "大阪", "大阪": "大阪", "大阪市": "大阪",
    "seoul": "首爾", "首爾": "首爾",
}
_COUNTRY_ALIAS = {
    "taiwan": "台灣", "台灣": "台灣", "臺灣": "台灣", "tw": "台灣",
    "japan": "日本", "日本": "日本", "jp": "日本",
    "korea": "韓國", "south korea": "韓國", "韓國": "韓國", "kr": "韓國",
}
_SUFFIXES = ["City", "city", "市", "縣", "都", "府", "県", "区", "區"]


def _strip_suffix(s: str) -> str:
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)].strip()
    return s.strip()


def canon(s: str | None) -> str:
    """正規化地名：先查別名，未命中則去行政後綴再查一次。回正規名或去後綴字串。"""
    if not s:
        return ""
    key = s.strip().lower()
    if key in _CITY_ALIAS:
        return _CITY_ALIAS[key]
    if key in _COUNTRY_ALIAS:
        return _COUNTRY_ALIAS[key]
    stripped = _strip_suffix(s.strip())
    k2 = stripped.lower()
    if k2 in _CITY_ALIAS:
        return _CITY_ALIAS[k2]
    if k2 in _COUNTRY_ALIAS:
        return _COUNTRY_ALIAS[k2]
    return stripped


def region_matches(query: str, country: str | None, city: str | None) -> bool:
    """查詢字串是否命中店家的國家或城市（正規化後等於或互相包含）。"""
    q = canon(query)
    if not q:
        return False
    for field in (country, city):
        c = canon(field)
        if c and (q == c or q in c or c in q):
            return True
    return False


def parse_address_components(components: list[dict] | None) -> dict:
    """Places (New) addressComponents → {country, city, district}。

    component 形如 {"longText":..., "shortText":..., "types":[...]}。
    city 優先序：locality > administrative_area_level_1 > administrative_area_level_2。
    """
    by_type: dict[str, str] = {}
    for comp in components or []:
        text = comp.get("longText") or comp.get("shortText")
        if not text:
            continue
        for t in comp.get("types", []):
            by_type.setdefault(t, text)

    country = canon(by_type.get("country"))
    city = canon(
        by_type.get("locality")
        or by_type.get("administrative_area_level_1")
        or by_type.get("administrative_area_level_2")
    )
    district = by_type.get("sublocality") or by_type.get("administrative_area_level_3")
    return {
        "country": country or None,
        "city": city or None,
        "district": district,
    }
```

- [ ] **Step 5: 跑測試確認通過**

Run: `docker compose exec -T app pytest tests/test_food_regions.py -v`
Expected: PASS（7 passed）

- [ ] **Step 6: Commit**

```bash
git add food/__init__.py food/regions.py tests/test_food_regions.py
git commit -m "feat(food): region normalization + matching (pure)"
```

---

## Task 3: food/places.py（Places API 薄封裝）

**Files:**
- Create: `food/places.py`

> I/O 邊界，不寫單元測試；用真實 API 手動驗證（Phase 0 已證明 key 可用）。

- [ ] **Step 1: 實作 `food/places.py`**

```python
"""Google Places API (New) 薄封裝。I/O 邊界，不單測。"""
import os
import json
import urllib.request

from food.regions import parse_address_components

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.addressComponents"
)


def search_text(query: str) -> dict | None:
    """用文字查最相關的一家店。回正規化後的 dict，查無回 None。"""
    key = os.getenv("GOOGLE_PLACES_SERVER_KEY")
    if not key:
        raise RuntimeError("GOOGLE_PLACES_SERVER_KEY 未設定")
    body = json.dumps(
        {"textQuery": query, "languageCode": "zh-TW", "maxResultCount": 1}
    ).encode("utf-8")
    req = urllib.request.Request(
        _SEARCH_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": _FIELD_MASK,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    places = data.get("places") or []
    if not places:
        return None
    p = places[0]
    region = parse_address_components(p.get("addressComponents"))
    loc = p.get("location") or {}
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text"),
        "address": p.get("formattedAddress"),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "country": region["country"],
        "city": region["city"],
        "district": region["district"],
    }


def maps_url(place_id: str) -> str:
    """由 place_id 組 Google Maps 連結（導航/查看用）。"""
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"
```

- [ ] **Step 2: 重啟並手動驗證真實查詢**

Run: `docker compose restart app`
Run:
```bash
docker compose exec -T app python -c "from food.places import search_text; import json; print(json.dumps(search_text('鼎泰豐 信義'), ensure_ascii=False, indent=2))"
```
Expected：印出含 `place_id` / `name=鼎泰豐 信義店` / `country=台灣` / `city=台北市` 的 dict。

- [ ] **Step 3: Commit**

```bash
git add food/places.py
git commit -m "feat(food): Places API (New) text search wrapper"
```

---

## Task 4: food/repo.py（FoodPlace DB 存取）

**Files:**
- Create: `food/repo.py`

> DB I/O，不寫單元測試；以手動驗證確認。沿用現有 `SessionLocal()` + try/finally 慣例。

- [ ] **Step 1: 實作 `food/repo.py`**

```python
"""FoodPlace 的 DB 存取（沿用 SessionLocal 慣例）。"""
from database import SessionLocal
from models import FoodPlace


def to_dict(rec: FoodPlace) -> dict:
    """ORM → dict，供 embed / recommend 純函式使用。"""
    return {
        "id": rec.id,
        "name": rec.name,
        "address": rec.address,
        "lat": rec.lat,
        "lng": rec.lng,
        "place_id": rec.place_id,
        "country": rec.country,
        "city": rec.city,
        "district": rec.district,
        "cuisine_type": rec.cuisine_type,
        "recommended_items": rec.recommended_items,
        "caution_summary": rec.caution_summary,
        "status": rec.status,
        "my_rating": rec.my_rating,
        "my_note": rec.my_note,
        "source_url": rec.source_url,
        "created_at": rec.created_at.isoformat() if rec.created_at else "",
    }


def upsert_place(place: dict, *, recommended_items=None, cuisine_type=None,
                 source_url=None) -> tuple[dict, bool]:
    """以 place_id 去重。回 (dict, created)；created=False 表示更新既有店。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.place_id == place["place_id"]).first()
        created = rec is None
        if rec is None:
            rec = FoodPlace(place_id=place["place_id"], status="想去")
            db.add(rec)
        # 基本欄位每次都用最新 Places 結果更新
        rec.name = place["name"]
        rec.address = place.get("address")
        rec.lat = place.get("lat")
        rec.lng = place.get("lng")
        rec.country = place.get("country")
        rec.city = place.get("city")
        rec.district = place.get("district")
        if recommended_items:
            rec.recommended_items = recommended_items
        if cuisine_type:
            rec.cuisine_type = cuisine_type
        if source_url:
            rec.source_url = source_url
        db.commit()
        db.refresh(rec)
        return to_dict(rec), created
    finally:
        db.close()


def list_places(status: str | None = None) -> list[dict]:
    """列出店家（可選狀態），新到舊。"""
    db = SessionLocal()
    try:
        q = db.query(FoodPlace)
        if status:
            q = q.filter(FoodPlace.status == status)
        rows = q.order_by(FoodPlace.created_at.desc()).all()
        return [to_dict(r) for r in rows]
    finally:
        db.close()


def set_visited(food_id: int, rating: int | None = None,
                note: str | None = None) -> dict | None:
    """把某筆標成『去過』，可帶評分/心得。查無回 None。"""
    db = SessionLocal()
    try:
        rec = db.query(FoodPlace).filter(FoodPlace.id == food_id).first()
        if rec is None:
            return None
        rec.status = "去過"
        if rating is not None:
            rec.my_rating = rating
        if note:
            rec.my_note = note
        db.commit()
        db.refresh(rec)
        return to_dict(rec)
    finally:
        db.close()
```

- [ ] **Step 2: 重啟並手動驗證 upsert + 去重 + set_visited**

Run: `docker compose restart app`
Run:
```bash
docker compose exec -T app python -c "
from food.places import search_text
from food.repo import upsert_place, list_places, set_visited
p = search_text('鼎泰豐 信義')
d1, c1 = upsert_place(p, recommended_items='小籠包', cuisine_type='中式')
print('first:', c1, d1['id'], d1['name'], d1['city'], d1['status'])
d2, c2 = upsert_place(p, recommended_items='蝦仁炒飯')
print('dup created? (應為 False):', c2, 'items=', d2['recommended_items'])
v = set_visited(d1['id'], rating=5, note='好吃')
print('visited:', v['status'], v['my_rating'], v['my_note'])
print('list 想去 count:', len(list_places('想去')))
"
```
Expected：`first: True ... 台北市 想去` / `dup created? False ... items= 蝦仁炒飯` / `visited: 去過 5 好吃` / 想去 count 0（已標去過）。

- [ ] **Step 3: 清掉測試資料**

Run:
```bash
docker compose exec -T app python -c "from database import SessionLocal; from models import FoodPlace; db=SessionLocal(); db.query(FoodPlace).delete(); db.commit(); db.close(); print('cleared')"
```
Expected: `cleared`

- [ ] **Step 4: Commit**

```bash
git add food/repo.py
git commit -m "feat(food): FoodPlace repo (upsert/list/set_visited)"
```

---

## Task 5: food/recommend.py（推薦篩選，純函式 TDD）

**Files:**
- Create: `food/recommend.py`
- Test: `tests/test_food_recommend.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_food_recommend.py`**

```python
from food.recommend import filter_for_recommendation, sort_recent, pick_random

PLACES = [
    {"name": "A", "country": "台灣", "city": "台中市", "status": "想去", "created_at": "2026-05-01"},
    {"name": "B", "country": "台灣", "city": "台中市", "status": "去過", "created_at": "2026-05-02"},
    {"name": "C", "country": "台灣", "city": "台北市", "status": "想去", "created_at": "2026-05-03"},
    {"name": "D", "country": "日本", "city": "大阪", "status": "想去", "created_at": "2026-05-04"},
]


def test_filter_only_wishlist_and_region():
    out = filter_for_recommendation(PLACES, "台中")
    names = {p["name"] for p in out}
    assert names == {"A"}          # B 已去過、C 在台北、D 在日本


def test_filter_by_country():
    out = filter_for_recommendation(PLACES, "日本")
    assert {p["name"] for p in out} == {"D"}


def test_sort_recent_desc():
    out = sort_recent(PLACES)
    assert [p["name"] for p in out] == ["D", "C", "B", "A"]


def test_pick_random_from_list():
    one = pick_random([PLACES[0]])
    assert one["name"] == "A"


def test_pick_random_empty():
    assert pick_random([]) is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `docker compose exec -T app pytest tests/test_food_recommend.py -v`
Expected: FAIL（`No module named 'food.recommend'`）

- [ ] **Step 3: 實作 `food/recommend.py`**

```python
"""美食推薦篩選/排序（純函式，無 I/O）。"""
import random

from food.regions import region_matches


def filter_for_recommendation(places: list[dict], query: str) -> list[dict]:
    """只留『想去』且國家或城市命中查詢的店。"""
    return [
        p for p in places
        if p.get("status") == "想去"
        and region_matches(query, p.get("country"), p.get("city"))
    ]


def sort_recent(places: list[dict]) -> list[dict]:
    """新到舊（依 created_at 字串，ISO 格式可直接字典序比較）。"""
    return sorted(places, key=lambda p: p.get("created_at") or "", reverse=True)


def pick_random(places: list[dict]) -> dict | None:
    """隨機挑一家（選擇困難救星）；空清單回 None。"""
    return random.choice(places) if places else None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `docker compose exec -T app pytest tests/test_food_recommend.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add food/recommend.py tests/test_food_recommend.py
git commit -m "feat(food): recommendation filter/sort/random (pure)"
```

---

## Task 6: discord_handler — embeds + 4 個 slash 指令

**Files:**
- Modify: `discord_handler.py`（顏色常數區、embed builder 區、`_register_commands()` 內）
- Modify: `README.md`、`CODEBASE.md`

> slash 指令是主動行為、不碰 `on_message`，故零風險。慢指令（查 Places / DB）一律先 `defer`。

- [ ] **Step 1: 加 `COLOR_FOOD` 常數**

在 `discord_handler.py` 既有顏色常數（`COLOR_WARN = ...` 那一區）後面加：

```python
COLOR_FOOD = 0xE67E22  # 美食橘
```

- [ ] **Step 2: 加三個 embed builder**

在 `discord_handler.py` 其他 `*_embed()` builder 附近新增。`p` 是 `food.repo.to_dict()` 的 dict：

```python
def food_place_embed(p: dict, *, created: bool = True) -> discord.Embed:
    from food.places import maps_url
    title = ("🍜 已加入想去" if created else "🍜 已更新（這家記過了）") + f"：{p['name']}"
    e = discord.Embed(title=title, color=COLOR_FOOD)
    if p.get("cuisine_type"):
        e.add_field(name="類型", value=p["cuisine_type"], inline=True)
    region = " / ".join(x for x in (p.get("country"), p.get("city")) if x) or "—"
    e.add_field(name="地區", value=region, inline=True)
    e.add_field(name="狀態", value=p.get("status", "想去"), inline=True)
    if p.get("address"):
        e.add_field(name="地址", value=p["address"], inline=False)
    if p.get("recommended_items"):
        e.add_field(name="推薦品項", value=p["recommended_items"], inline=False)
    if p.get("caution_summary"):
        e.add_field(name="⚠️ 雷點", value=p["caution_summary"], inline=False)
    if p.get("place_id"):
        e.add_field(name="地圖", value=maps_url(p["place_id"]), inline=False)
    e.set_footer(text=f"編號 {p['id']}")
    return e


def food_list_embed(places: list[dict], title: str) -> discord.Embed:
    e = discord.Embed(title=title, color=COLOR_FOOD)
    if not places:
        e.description = "（沒有符合的店家）"
        return e
    lines = []
    for p in places[:20]:
        cat = f" `{p['cuisine_type']}`" if p.get("cuisine_type") else ""
        items = f" — {p['recommended_items']}" if p.get("recommended_items") else ""
        lines.append(f"`#{p['id']}` **{p['name']}**{cat}{items}")
    e.description = "\n".join(lines)
    if len(places) > 20:
        e.set_footer(text=f"共 {len(places)} 家，只顯示前 20")
    return e


def food_reco_embed(query: str, places: list[dict], pick: dict | None) -> discord.Embed:
    e = food_list_embed(places, title=f"🍜 {query} 的想去清單（{len(places)} 家）")
    if pick:
        e.add_field(name="🎲 選擇困難？這家",
                    value=f"**{pick['name']}**" +
                          (f" — {pick['recommended_items']}" if pick.get("recommended_items") else ""),
                    inline=False)
    return e
```

- [ ] **Step 3: 在 `_register_commands()` 內加 4 個指令**

放在既有指令（例如 `cmd_help` 之前/之後皆可）旁：

```python
        @tree.command(name="美食新增", description="新增一家想去的店（自動查 Google 正規化）")
        @app_commands.describe(店名="店名", 區域="縣市/城市（幫助定位，選填）", 推薦品項="想吃什麼（選填）")
        async def cmd_food_add(ix: discord.Interaction, 店名: str, 區域: str = "", 推薦品項: str = ""):
            await ix.response.defer()
            from food.places import search_text
            from food.repo import upsert_place
            query = f"{店名} {區域}".strip()
            try:
                place = search_text(query)
            except Exception as ex:
                await ix.followup.send(embed=error_embed(f"查 Google 失敗：{ex}"))
                return
            if not place:
                await ix.followup.send(embed=error_embed(f"找不到「{query}」，換個更完整的店名或加上區域再試。"))
                return
            p, created = upsert_place(place, recommended_items=推薦品項 or None)
            await ix.followup.send(embed=food_place_embed(p, created=created))

        @tree.command(name="美食推薦", description="依縣市/國家推薦想去的店")
        @app_commands.describe(地區="縣市或國家，例如 台中 / 日本")
        async def cmd_food_reco(ix: discord.Interaction, 地區: str):
            await ix.response.defer()
            from food.repo import list_places
            from food.recommend import filter_for_recommendation, sort_recent, pick_random
            matched = sort_recent(filter_for_recommendation(list_places("想去"), 地區))
            pick = pick_random(matched)
            await ix.followup.send(embed=food_reco_embed(地區, matched, pick))

        @tree.command(name="美食清單", description="列出美食清單")
        @app_commands.describe(狀態="想去 / 去過（留空=全部）")
        async def cmd_food_list(ix: discord.Interaction, 狀態: str = ""):
            await ix.response.defer()
            from food.repo import list_places
            status = 狀態 if 狀態 in ("想去", "去過") else None
            places = list_places(status)
            title = f"🍜 美食清單（{狀態 or '全部'}，{len(places)} 家）"
            await ix.followup.send(embed=food_list_embed(places, title))

        @tree.command(name="去過", description="把某家標成去過（可記評分/心得）")
        @app_commands.describe(編號="店家編號", 評分="1-5（選填）", 心得="一句話（選填）")
        async def cmd_food_visited(ix: discord.Interaction, 編號: int, 評分: int = 0, 心得: str = ""):
            await ix.response.defer()
            from food.repo import set_visited
            rating = 評分 if 1 <= 評分 <= 5 else None
            p = set_visited(編號, rating=rating, note=心得 or None)
            if not p:
                await ix.followup.send(embed=error_embed(f"找不到編號 {編號}"))
                return
            await ix.followup.send(embed=food_place_embed(p, created=False))
```

- [ ] **Step 4: 重啟並驗證指令同步**

Run: `docker compose restart app`
Run: `docker compose logs app --tail=5`（確認無 import 錯誤、bot 正常啟動）
然後在 Discord 確認 `/美食新增`、`/美食推薦`、`/美食清單`、`/去過` 出現在指令選單。

- [ ] **Step 5: 在 Discord 實測一輪**

1. `/美食新增 店名:鼎泰豐 信義 推薦品項:小籠包` → 應回「已加入想去」卡片，地區=台灣/台北市，footer 有編號
2. `/美食推薦 地區:台北` → 應列出該店 + 🎲 隨機一家
3. `/去過 編號:<上面的編號> 評分:5 心得:好吃` → 應回「已更新」卡片、狀態=去過
4. `/美食清單 狀態:去過` → 應看到該店

- [ ] **Step 6: 更新 README / CODEBASE**

`README.md` 的 Discord slash 指令表新增 `/美食新增`、`/美食推薦`、`/美食清單`、`/去過` 四列（說明：美食地圖 Phase 1A — 手動建私人美食清單 + 縣市/國家推薦）。
`CODEBASE.md`：把「規劃中模組」的美食地圖條目標成「Phase 1A 已實作（slash 地基）」，並在 File Map 加 `food/`（regions/places/repo/recommend）與 `FoodPlace` 表；slash 指令數從 16 改為 20。

- [ ] **Step 7: Commit**

```bash
git add discord_handler.py README.md CODEBASE.md
git commit -m "feat(food): Discord slash commands for food list + recommend"
```

---

## 完成標準（Plan A）

- [ ] `food_places` 表存在
- [ ] `pytest tests/` 全綠（含 regions、recommend 新測試）
- [ ] Discord 可用 `/美食新增` 建店、`/美食推薦` 查到、`/去過` 改狀態、`/美食清單` 列出
- [ ] 完全沒動到 `on_message` 與現有記帳行為

Plan B（截圖自動抽取 + 頻道分流 + reply 補件 + ✅ + 雷點摘要）另開一份計畫。
