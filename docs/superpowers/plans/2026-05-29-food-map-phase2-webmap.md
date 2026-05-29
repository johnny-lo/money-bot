# 美食地圖 Phase 2（Google Maps 網頁）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/美食地圖` slash 指令產生一次性 token 連結 → 開一個唯讀 Google Maps 網頁，把「想去」店家標藍 pin、「去過」標綠 pin，點 pin 看詳情，並可前端切換只看想去/去過。

**Architecture:** 大量重用既有機制——`auth` 一次性 token、`routes/report.py` 的「HTML 頁自驗 token + API 用 `Depends(require_token)`」雙路由模式、`templates/report.html` 的前端骨架（token 取法 / `withToken` / fetch 錯誤處理 / esc）、`food.repo.list_places()`、`food.places.maps_url()`。新增一層純函式 `food/map_data.py` 把 DB dict 整形成前端 marker 用的精簡 JSON（唯一可單測），其餘 route/HTML 為 I/O 手動驗證。前端用 Google Maps JS inline bootstrap loader + `AdvancedMarkerElement`/`PinElement`。

**Tech Stack:** FastAPI、Google Maps JavaScript API（`AdvancedMarkerElement`）、既有 token 機制、pytest。

> 對應 spec：`docs/superpowers/specs/2026-05-23-food-map-module-design.md` §6.3 地圖呈現。
> 設計來源：Phase 2 設計研究 workflow（wf_9df7a39b-7f6）。
> **已定決策**：① 不做 clustering；② InfoWindow **不顯示雷點** `caution_summary`（也不從 API 回傳）；③ 做想去/去過前端 toggle（隱藏 marker、不重抓 API）；④ 不做 `?focus` 地區聚焦。
> 專案慣例：每次 commit 同步更新 `README.md` / `CODEBASE.md`（Task 8）。

---

## Phase 2-0 事前清單（寫 code 前，使用者手動做）

> 比照 Phase 0：全是 Google Cloud 設定 + 填 env，不動程式。完成後把兩個值填進 `.env` 再開工。
> 這是 Phase 1 刻意延後的 **browser key**（前端用、會曝在 HTML，靠限制防濫用）。

- [ ] Google Cloud Console（用現有已綁帳單的同一專案）→ 啟用 **Maps JavaScript API**
- [ ] Credentials → 建**新的** API key（**不要**和 `GOOGLE_PLACES_SERVER_KEY` 共用）
- [ ] 該 key → Application restrictions → **HTTP referrers** → 填 `https://your-ngrok-domain.ngrok-free.dev/*`（網域層 + `/*`，**不要**鎖到 `/food/map` 子路徑，瀏覽器會 strip path 導致合法請求被拒）
- [ ] 該 key → API restrictions → Restrict key → **只勾 Maps JavaScript API**
- [ ] Google Maps Platform → Quotas → Maps JavaScript API → 每日上限 **200/日**（硬煞車；200×30 < 免費 10,000/月）
- [ ] Billing → Budgets & alerts → 建 **US$1** budget、threshold 50/90/100%、收件 fox4961166@gmail.com
- [ ] （選）Map Management → 建正式 **Map ID**（否則用 `DEMO_MAP_ID` 會有「For development purposes only」浮水印）
- [ ] 填 `.env`：`GOOGLE_MAPS_BROWSER_KEY=...`、`GOOGLE_MAPS_MAP_ID=...`（沒申請就填 `DEMO_MAP_ID`）
- [ ] 確認 ngrok 當前子網域與 `discord_handler.py` 的 `NGROK_DOMAIN` 一致；若已變動先同步再設 referrer，設好等約 5 分鐘 propagation

> 成本結論：Dynamic Maps 個人用量預期 **US$0/月**（免費 10,000 次/月、與 Places API 分開計）。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `food/map_data.py` | 建立 | `build_map_places(places)` 純函式：過濾無座標、整形 marker JSON、status→visited、組 maps_url |
| `tests/test_food_map_data.py` | 建立 | `build_map_places` 單元測試 |
| `routes/food_map.py` | 建立 | `GET /api/food/places`（token）+ `GET /food/map`（HTML、注入 key/mapId） |
| `templates/food_map.html` | 建立 | Maps JS 前端：藍/綠 pin、共用 InfoWindow、fitBounds、想去/去過 toggle |
| `main.py` | 修改 | `include_router(food_map_router)` |
| `discord_handler.py` | 修改 | `food_map_embed()` + `/美食地圖` slash 指令 |
| `docker-compose.yml` | 修改 | 注入 `GOOGLE_MAPS_BROWSER_KEY` / `GOOGLE_MAPS_MAP_ID` |
| `README.md` / `CODEBASE.md` | 修改 | 文件 |

測試：`docker compose exec -T app pytest tests/ -v`
套用：`docker compose restart app`

---

## Task 1: `food/map_data.py` 整形（純函式 TDD）

**Files:**
- Create: `food/map_data.py`
- Test: `tests/test_food_map_data.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_food_map_data.py`**

```python
from food.map_data import build_map_places


def test_filters_out_no_coordinates():
    places = [
        {"id": 1, "name": "A", "status": "想去", "lat": 25.0, "lng": 121.5, "place_id": "p1"},
        {"id": 2, "name": "B", "status": "想去", "lat": None, "lng": 121.5, "place_id": "p2"},
        {"id": 3, "name": "C", "status": "想去", "lat": 25.0, "lng": None, "place_id": "p3"},
    ]
    out = build_map_places(places)
    assert [p["id"] for p in out] == [1]


def test_visited_bool_from_status():
    places = [
        {"id": 1, "name": "A", "status": "去過", "lat": 25.0, "lng": 121.5, "place_id": "p1"},
        {"id": 2, "name": "B", "status": "想去", "lat": 25.1, "lng": 121.6, "place_id": "p2"},
    ]
    out = build_map_places(places)
    assert out[0]["visited"] is True
    assert out[1]["visited"] is False


def test_maps_url_uses_place_id_when_present():
    out = build_map_places([
        {"id": 1, "name": "鼎泰豐", "status": "想去", "lat": 25.0, "lng": 121.5, "place_id": "ChIJ_abc"},
    ])
    assert "query_place_id=ChIJ_abc" in out[0]["maps_url"]


def test_maps_url_fallback_to_coords_when_no_place_id():
    out = build_map_places([
        {"id": 1, "name": "無 id 店", "status": "想去", "lat": 25.5, "lng": 121.2, "place_id": None},
    ])
    assert "query=25.5,121.2" in out[0]["maps_url"]
    assert "query_place_id" not in out[0]["maps_url"]


def test_no_caution_summary_in_output():
    out = build_map_places([
        {"id": 1, "name": "A", "status": "想去", "lat": 25.0, "lng": 121.5,
         "place_id": "p1", "caution_summary": "很雷"},
    ])
    assert "caution_summary" not in out[0]


def test_output_fields_and_empty():
    assert build_map_places([]) == []
    out = build_map_places([
        {"id": 7, "name": "店", "status": "想去", "lat": 25.0, "lng": 121.5, "place_id": "p1",
         "cuisine_type": "拉麵", "recommended_items": "豚骨", "my_rating": 4,
         "my_note": "讚", "address": "台北市"},
    ])
    assert set(out[0].keys()) == {
        "id", "name", "status", "visited", "lat", "lng",
        "cuisine_type", "recommended_items", "my_rating", "my_note", "address", "maps_url",
    }
```

- [ ] **Step 2: 跑測試確認失敗**

`docker compose exec -T app pytest tests/test_food_map_data.py -v` → `ModuleNotFoundError: No module named 'food.map_data'`

- [ ] **Step 3: 實作 `food/map_data.py`**

```python
"""把 FoodPlace dict 整形成前端地圖 marker 用的精簡 JSON（純函式，無 I/O）。

決策：不含 caution_summary（地圖只給正面資訊）；過濾掉無座標的店。
"""
from food.places import maps_url


def build_map_places(places: list[dict]) -> list[dict]:
    """過濾無 lat/lng 的店，整形成 marker 需要的精簡欄位。"""
    out: list[dict] = []
    for p in places:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        place_id = p.get("place_id")
        if place_id:
            url = maps_url(place_id, p.get("name") or "")
        else:
            url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "status": p.get("status"),
            "visited": p.get("status") == "去過",
            "lat": lat,
            "lng": lng,
            "cuisine_type": p.get("cuisine_type"),
            "recommended_items": p.get("recommended_items"),
            "my_rating": p.get("my_rating"),
            "my_note": p.get("my_note"),
            "address": p.get("address"),
            "maps_url": url,
        })
    return out
```

- [ ] **Step 4: 跑測試確認通過**

`docker compose exec -T app pytest tests/test_food_map_data.py -v` → 6 passed.

- [ ] **Step 5: Commit**

```bash
git add food/map_data.py tests/test_food_map_data.py
git commit -m "feat(food): build_map_places — shape FoodPlace for map markers (pure)"
```

---

## Task 2: `routes/food_map.py` API + HTML 路由

**Files:**
- Create: `routes/food_map.py`

> I/O 路由，不寫單元測試；用 curl/python 手動驗證 token 保護與注入。

- [ ] **Step 1: 實作 `routes/food_map.py`**

```python
"""美食地圖：HTML 頁（自驗 token）+ 店家 JSON API（Depends token）。"""
import os
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse

from auth import validate_report_token, require_token
from food.repo import list_places
from food.map_data import build_map_places

router = APIRouter()


@router.get("/api/food/places", dependencies=[Depends(require_token)])
def api_food_places(status: str = Query(None)):
    """回傳地圖用的店家清單。status 選填（想去/去過），省略=全部。"""
    s = status if status in ("想去", "去過") else None
    return {"places": build_map_places(list_places(s))}


@router.get("/food/map", response_class=HTMLResponse)
def food_map_page(token: str = Query(None)):
    """美食地圖頁面（需有效 token；把 browser key / mapId 注入 HTML）。"""
    if not token or not validate_report_token(token):
        raise HTTPException(status_code=401, detail="無效或過期的連結，請重新用 /美食地圖 取得連結。")
    with open("templates/food_map.html", "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__BROWSER_KEY__", os.getenv("GOOGLE_MAPS_BROWSER_KEY", ""))
    html = html.replace("__MAP_ID__", os.getenv("GOOGLE_MAPS_MAP_ID", "DEMO_MAP_ID"))
    return html
```

- [ ] **Step 2: 先建一個最小 `templates/food_map.html` 佔位（Task 5 才寫完整版），讓路由能讀檔**

```bash
printf '<!DOCTYPE html><html><body>map placeholder key=__BROWSER_KEY__ mapid=__MAP_ID__</body></html>' > templates/food_map.html
```

- [ ] **Step 3: main.py 掛上路由**（與 Task 4 同步，這裡先做以便驗證）

在 `main.py` import 區（`from routes.report import ...` 附近）加：
```python
from routes.food_map import router as food_map_router
```
在 `app.include_router(record_router)` 之後加：
```python
app.include_router(food_map_router)
```

- [ ] **Step 4: 重啟 + 驗證 token 保護與注入**

```bash
docker compose restart app
# 無 token → 401
docker compose exec -T app python -c "
import urllib.request, urllib.error
for path in ['/food/map', '/api/food/places']:
    try:
        urllib.request.urlopen('http://localhost:8000'+path, timeout=5)
        print(path, 'NO-AUTH OK (應該不會到這)')
    except urllib.error.HTTPError as e:
        print(path, '->', e.code)
"
# 有 token → HTML 注入成功（用 python 直接產 token）
docker compose exec -T app python -c "
from auth import generate_report_token
import urllib.request
t = generate_report_token('test')
html = urllib.request.urlopen(f'http://localhost:8000/food/map?token={t}', timeout=5).read().decode()
print('key 已注入:', '__BROWSER_KEY__' not in html)
print('mapid 已注入:', '__MAP_ID__' not in html)
import json
data = json.loads(urllib.request.urlopen(f'http://localhost:8000/api/food/places?token={t}', timeout=5).read())
print('api places key:', 'places' in data)
"
```
Expected：兩路由無 token 都回 `401`；有 token 時 `key 已注入: True`、`mapid 已注入: True`、`api places key: True`。

- [ ] **Step 5: Commit**

```bash
git add routes/food_map.py templates/food_map.html main.py
git commit -m "feat(food): /food/map + /api/food/places routes (token-guarded)"
```

---

## Task 3: `templates/food_map.html` 完整前端

**Files:**
- Modify: `templates/food_map.html`（用完整版覆蓋 Task 2 的佔位）

> 沿用 `report.html` 的 token 取法 / `withToken` / fetch 錯誤處理 / esc。前端 toggle 用隱藏 marker（不重抓 API）。

- [ ] **Step 1: 用以下完整內容覆蓋 `templates/food_map.html`**

```html
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>美食地圖</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        #map { width: 100%; height: 100%; }
        #toolbar {
            position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
            z-index: 5; display: flex; gap: 8px; background: rgba(255,255,255,0.92);
            padding: 8px 10px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }
        #toolbar button {
            border: none; border-radius: 8px; padding: 6px 14px; font-size: 0.95rem;
            cursor: pointer; background: #eee; color: #333;
        }
        #toolbar button.active { background: #E67E22; color: #fff; }
        #msg {
            position: fixed; top: 60px; left: 50%; transform: translateX(-50%);
            z-index: 5; background: rgba(0,0,0,0.7); color: #fff; padding: 8px 14px;
            border-radius: 8px; display: none;
        }
        .iw h3 { margin-bottom: 6px; font-size: 1.05rem; }
        .iw p { margin: 2px 0; font-size: 0.9rem; color: #444; }
        .iw a { color: #1a73e8; text-decoration: none; font-size: 0.9rem; }
    </style>
</head>
<body>
    <div id="toolbar">
        <button id="btn-all" class="active" onclick="setFilter('all')">全部</button>
        <button id="btn-wish" onclick="setFilter('想去')">想去</button>
        <button id="btn-visited" onclick="setFilter('去過')">去過</button>
    </div>
    <div id="msg"></div>
    <div id="map"></div>

    <script>
        const TOKEN = new URLSearchParams(window.location.search).get('token') || '';
        function withToken(url) {
            const sep = url.includes('?') ? '&' : '?';
            return url + sep + 'token=' + encodeURIComponent(TOKEN);
        }
        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }
        function showMsg(t) { const m = document.getElementById('msg'); m.textContent = t; m.style.display = 'block'; }

        let MARKERS = [];   // {marker, status}
        let infoWindow = null;

        // Google Maps inline bootstrap loader（官方）
        (g => { var h, a, k, p = "The Google Maps JavaScript API", c = "google", l = "importLibrary", q = "__ib__", m = document, b = window; b = b[c] || (b[c] = {}); var d = b.maps || (b.maps = {}), r = new Set, e = new URLSearchParams, u = () => h || (h = new Promise(async (f, n) => { await (a = m.createElement("script")); e.set("libraries", [...r] + ""); for (k in g) e.set(k.replace(/[A-Z]/g, t => "_" + t[0].toLowerCase()), g[k]); e.set("callback", c + ".maps." + q); a.src = `https://maps.${c}apis.com/maps/api/js?` + e; d[q] = f; a.onerror = () => h = n(Error(p + " could not load.")); a.nonce = m.querySelector("script[nonce]")?.nonce || ""; m.head.append(a) })); d[l] ? console.warn(p + " only loads once. Ignoring:", g) : d[l] = (f, ...n) => r.add(f) && u().then(() => d[l](f, ...n)) })({
            key: "__BROWSER_KEY__",
            v: "weekly",
        });

        async function initMap() {
            const { Map, InfoWindow } = await google.maps.importLibrary("maps");
            const { AdvancedMarkerElement, PinElement } = await google.maps.importLibrary("marker");

            const map = new Map(document.getElementById("map"), {
                center: { lat: 23.7, lng: 121 },  // 台灣中心，待 fitBounds 覆蓋
                zoom: 7,
                mapId: "__MAP_ID__",
                mapTypeControl: false,
                streetViewControl: false,
            });
            infoWindow = new InfoWindow();

            let data;
            try {
                const res = await fetch(withToken('/api/food/places'));
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    showMsg('載入失敗：' + (err.detail || res.status));
                    return;
                }
                data = await res.json();
            } catch (e) {
                showMsg('載入失敗：' + e);
                return;
            }

            const places = data.places || [];
            if (!places.length) { showMsg('目前沒有有座標的店家'); return; }

            const bounds = new google.maps.LatLngBounds();
            for (const pl of places) {
                const pin = new PinElement(pl.visited
                    ? { background: '#137333', borderColor: '#0d652d', glyphColor: 'white' }
                    : { background: '#1f7dd4', borderColor: '#0d47a1', glyphColor: 'white' });
                const marker = new AdvancedMarkerElement({
                    map, position: { lat: pl.lat, lng: pl.lng },
                    title: pl.name || '', content: pin.element, gmpClickable: true,
                });
                marker.addListener('click', () => {
                    infoWindow.setContent(buildContent(pl));
                    infoWindow.open({ anchor: marker, map });
                });
                MARKERS.push({ marker, status: pl.status });
                bounds.extend({ lat: pl.lat, lng: pl.lng });
            }
            map.fitBounds(bounds);
            if (places.length === 1) {
                google.maps.event.addListenerOnce(map, 'idle', () => {
                    if (map.getZoom() > 16) map.setZoom(16);
                });
            }
        }

        function buildContent(pl) {
            let h = '<div class="iw">';
            h += '<h3>' + esc(pl.name) + '</h3>';
            if (pl.cuisine_type) h += '<p>🍽️ ' + esc(pl.cuisine_type) + '</p>';
            if (pl.recommended_items) h += '<p>👍 ' + esc(pl.recommended_items) + '</p>';
            if (pl.my_rating) h += '<p>⭐ ' + '★'.repeat(pl.my_rating) + '</p>';
            if (pl.my_note) h += '<p>📝 ' + esc(pl.my_note) + '</p>';
            if (pl.address) h += '<p>📍 ' + esc(pl.address) + '</p>';
            if (pl.maps_url) h += '<p><a href="' + esc(pl.maps_url) + '" target="_blank" rel="noopener">在 Google Maps 開啟</a></p>';
            h += '</div>';
            return h;
        }

        function setFilter(f) {
            for (const id of ['all', 'wish', 'visited']) {
                document.getElementById('btn-' + id).classList.remove('active');
            }
            document.getElementById('btn-' + (f === 'all' ? 'all' : f === '想去' ? 'wish' : 'visited')).classList.add('active');
            for (const m of MARKERS) {
                const show = (f === 'all') || (m.status === f);
                m.marker.map = show ? m.marker.map || null : null;
            }
            // 重新指定 map（隱藏=null，顯示=透過閉包重設）
        }

        initMap();
    </script>
</body>
</html>
```

> 注意 `setFilter` 隱藏/顯示需要保留 map 參照。改用下方修正版的 `setFilter`（Step 2 修正）以正確切換。

- [ ] **Step 2: 修正 `setFilter`（marker 需保留 map 參照才能重新顯示）**

把上面 `setFilter` 整段換成下列版本，並在 `initMap` 內把 `const map = ...` 改成 `window._map = ...`（讓 setFilter 取得 map）：

在 `initMap` 內：
```javascript
            const map = new Map(document.getElementById("map"), {
```
改為：
```javascript
            const map = window._map = new Map(document.getElementById("map"), {
```

`setFilter` 換成：
```javascript
        function setFilter(f) {
            for (const id of ['all', 'wish', 'visited']) {
                document.getElementById('btn-' + id).classList.remove('active');
            }
            const btn = f === 'all' ? 'all' : (f === '想去' ? 'wish' : 'visited');
            document.getElementById('btn-' + btn).classList.add('active');
            for (const m of MARKERS) {
                const show = (f === 'all') || (m.status === f);
                m.marker.map = show ? window._map : null;
            }
        }
```

- [ ] **Step 3: 重啟（HTML 改動容器靠 bind mount 即時生效，但保險起見重啟）**

```bash
docker compose restart app
```

- [ ] **Step 4: 真人瀏覽器驗證（這步只能人工，subagent 無法）**

1. 確認 DB 至少有 2 筆有座標的店（1 想去、1 去過）。沒有的話先在 `#美食輸入` 丟兩家或用 `/美食新增`。
2. Discord 打 `/美食地圖`（Task 6 完成後）或直接：
   ```bash
   docker compose exec -T app python -c "from auth import generate_report_token; print('https://your-ngrok-domain.ngrok-free.dev/food/map?token='+generate_report_token('me'))"
   ```
   把連結貼到瀏覽器（30 分鐘有效）。
3. 驗收：藍 pin=想去、綠 pin=去過；點 pin 跳資訊視窗（店名/類型/推薦/評分/心得/地址/Google Maps 連結，**無雷點**）；自動框景；上方「全部 / 想去 / 去過」切換能隱藏/顯示對應 pin。
4. 用含 `<` `>` 特殊字元的店名建一筆，確認 InfoWindow 不破版（esc 生效）。

- [ ] **Step 5: Commit**

```bash
git add templates/food_map.html
git commit -m "feat(food): map webpage — blue/green pins, infowindow, fitBounds, status toggle"
```

---

## Task 4: 確認 `main.py` 路由已掛載

> Task 2 Step 3 已加。這個 task 純驗證 + 補漏。

- [ ] **Step 1: 確認 `main.py` 有兩行**

```bash
grep -n "food_map_router" main.py
```
Expected：import 一行 + `include_router` 一行。若缺則補（見 Task 2 Step 3）。

- [ ] **Step 2: 確認全測試 + 路由存在**

```bash
docker compose exec -T app pytest tests/ -q
docker compose exec -T app python -c "
import urllib.request, urllib.error
try: urllib.request.urlopen('http://localhost:8000/api/food/places', timeout=5)
except urllib.error.HTTPError as e: print('/api/food/places ->', e.code, '(401 表示已掛載+受保護)')
"
```
Expected：測試 ≥ 75 passed（69 + 6 map_data）；`/api/food/places -> 401`。

- [ ] **Step 3: 若有改動才 commit**（Task 2 已 commit main.py，通常此處無改動）

---

## Task 5: discord `/美食地圖` 指令 + embed

**Files:**
- Modify: `discord_handler.py`

- [ ] **Step 1: 在 `discord_handler.py` 的 `food_reco_embed` / `food_missing_embed` 附近新增 embed builder**

```python
def food_map_embed(url: str) -> discord.Embed:
    return discord.Embed(
        title="🗺️ 美食地圖",
        description=f"[👉 點此開啟地圖]({url})\n_30 分鐘內有效_\n藍 = 想去、綠 = 去過",
        color=COLOR_FOOD,
    )
```

- [ ] **Step 2: 在 `_register_commands()` 內、`/去過` 指令旁新增 slash 指令**

```python
        @tree.command(name="美食地圖", description="開啟想去/去過的美食地圖")
        async def cmd_food_map(ix: discord.Interaction):
            token = generate_report_token(str(ix.user.id))
            url = f"{BASE_URL}/food/map?token={token}"
            await ix.response.send_message(embed=food_map_embed(url))
```

> `generate_report_token` 與 `BASE_URL` 已在 `discord_handler.py` 既有 import / 常數（`cmd_report` 同款）。

- [ ] **Step 3: 重啟 + 驗證**

```bash
docker compose restart app
docker compose logs app --tail=8
docker compose exec -T app python -c "
import discord_handler as dh
print('embed ok:', type(dh.food_map_embed('http://x')).__name__ == 'Embed')
"
```
Expected：`embed ok: True`；log 無 traceback、bot 上線。Discord 指令列表出現 `/美食地圖`（restart 會 re-sync）。

- [ ] **Step 4: Discord 實測**：打 `/美食地圖` → 收到橘色 embed → 點連結開地圖（含 Task 3 的驗收）。

- [ ] **Step 5: Commit**

```bash
git add discord_handler.py
git commit -m "feat(food): /美食地圖 slash command + map embed"
```

---

## Task 6: `docker-compose.yml` 注入 browser key / mapId

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: 在 `app.environment:` 區（`GOOGLE_PLACES_SERVER_KEY` 同層）新增兩行**

```yaml
      - GOOGLE_MAPS_BROWSER_KEY=${GOOGLE_MAPS_BROWSER_KEY:-}
      - GOOGLE_MAPS_MAP_ID=${GOOGLE_MAPS_MAP_ID:-DEMO_MAP_ID}
```

- [ ] **Step 2: 確認 `.env` 已有這兩個值**（Phase 2-0 清單填的）

```bash
grep -E "GOOGLE_MAPS_BROWSER_KEY|GOOGLE_MAPS_MAP_ID" .env || echo "⚠️ .env 缺，請先補（見 Phase 2-0）"
```

- [ ] **Step 3: recreate 讓新 env 進容器並驗證**

```bash
docker compose up -d app
docker compose exec -T app sh -c '
for v in GOOGLE_MAPS_BROWSER_KEY GOOGLE_MAPS_MAP_ID; do
  eval val=\$$v
  if [ -n "$val" ]; then echo "$v: ✅ (len ${#val})"; else echo "$v: ❌ 空"; fi
done'
```
Expected：兩者皆有值（BROWSER_KEY 長度 ~39；MAP_ID 至少是 `DEMO_MAP_ID`）。

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "chore(food): inject GOOGLE_MAPS_BROWSER_KEY / MAP_ID into container"
```

---

## Task 7: 端到端 live 驗證（人工）

> 這是合併前的把關，subagent 無法代勞。

- [ ] DB 有 ≥2 筆有座標的店（想去 + 去過各一）
- [ ] Discord `/美食地圖` → 橘 embed → 點連結
- [ ] 地圖：藍/綠 pin 正確、點 pin 出 InfoWindow（無雷點欄位）、自動框景
- [ ] 「全部 / 想去 / 去過」toggle 正常隱藏/顯示
- [ ] 從**錯誤**網域（localhost）開應出 `RefererNotAllowedMapError`（驗證 referrer 限制生效）
- [ ] 含特殊字元店名不破版
- [ ] 既有功能無回歸（`/報表`、記帳照常）

---

## Task 8: 文件 + 最終 commit

**Files:**
- Modify: `README.md`、`CODEBASE.md`

- [ ] **Step 1: README** — 「美食地圖」段落加 `/美食地圖`：開 Google Maps 網頁、藍=想去/綠=去過、點 pin 看詳情、可切換想去/去過；環境變數表加 `GOOGLE_MAPS_BROWSER_KEY`、`GOOGLE_MAPS_MAP_ID`。

- [ ] **Step 2: CODEBASE** — File Map 加 `food/map_data.py`、`routes/food_map.py`、`templates/food_map.html`；slash 指令數 20→21；env 清單補兩個 key；「規劃中模組」美食地圖條目標記「Phase 2 地圖網頁已實作」。

- [ ] **Step 3: Commit**

```bash
git add README.md CODEBASE.md
git commit -m "docs(food): Phase 2 web map (/美食地圖, /food/map, browser key)"
```

---

## 完成標準（Phase 2）

- [ ] `pytest tests/` 全綠（≥ 75：69 + 6 map_data）
- [ ] 無 token 打 `/food/map`、`/api/food/places` 皆 401
- [ ] Discord `/美食地圖` 開出地圖，藍/綠 pin + InfoWindow + toggle 正常
- [ ] referrer 限制生效（錯網域被擋）
- [ ] 既有功能無回歸

通過後進 `superpowers:finishing-a-development-branch` 合併。
