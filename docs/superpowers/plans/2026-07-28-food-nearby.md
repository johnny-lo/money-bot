# 美食「附近有什麼」實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓美食頁預設先問「你願意跑多遠」，再用帶家數的料理磚塊回答「這附近有哪些選擇」，點磚塊才看店。

**Architecture:** 純前端。`/api/food/places` 已回傳 `lat/lng` 與 `cuisine_major`，所以定位、距離、分組全在裝置上算——零後端改動、零 API 成本、拉滑桿即時反應、離線可用。純函式住 `geo.js`，畫面住 `Nearby.jsx`（純呈現，不自己定位也不抓資料），狀態與定位流程留在 `Food.jsx`（資料的唯一主人），與現有 `FoodList`/`FoodMap` 分工一致。

**Tech Stack:** React 18 + Vite（無狀態管理庫）、瀏覽器 Geolocation API、容器內 Playwright 做端對端驗證。

**Spec:** `docs/superpowers/specs/2026-07-28-food-nearby-design.md`

## Global Constraints

- **不改後端。** payload 已含 `lat`/`lng`/`cuisine_major`/`cuisine_minor`/`district`。任何需要改 Python 的想法都代表理解錯了設計。
- **前端 build 在 host 跑**：`npm run build --prefix frontend`。live-mount 直接生效，**不用重啟容器**。
- **`frontend/dist` 被 gitignore** → 只 commit `frontend/src`。
- **repo 沒有 JS 測試框架**（已確認 `frontend/package.json` 無 vitest/jest、零測試檔）。紅綠燈這樣做：
  - 純函式 → `node --input-type=module -e "..."` 直接 import 專案模組驗（已實測可行）
  - UI → 容器內 Playwright（`docker exec money-bot python /tmp/xxx.py`）
  - 手機視覺 → **使用者親眼確認**，不可自行宣稱完成（AGENTS.md §4）
- **範圍檔位與車程標註是手工校準的常數，不是公式**：1km→5分、3km→10分、5km→15分、10km→20分、30km→40分。線性公式會把 30km 算成 90 分（實際約 40 分，長程走國道），使用者看到就永遠不會按那一檔。
- **預設範圍 5 km。**
- **定位失敗必須自動退回清單模式**，不可彈窗擋路、不可卡住首屏。
- README + CODEBASE 在最後一個 task 統一更新（照本 repo 慣例：逐步 TDD commit 不動文件）。

---

### Task 1: `geo.js` — 距離與分組純函式

**Files:**
- Create: `frontend/src/geo.js`

**Interfaces:**
- Consumes: 無（無依賴的葉節點模組）
- Produces:
  - `RANGES: Array<{km: number, label: string, minutes: number}>` — 五個檔位，由小到大
  - `DEFAULT_RANGE_KM: number` = 5
  - `OTHER: string` = `'其他'`
  - `haversineKm(a: {lat, lng}, b: {lat, lng}): number` — 任一為 falsy 時回 `Infinity`
  - `groupByMajor(places: Array<{cuisine_major}>): Array<{major: string, count: number}>` — 家數多的在前，`其他` 永遠最後

- [ ] **Step 1: 寫檢查腳本（先失敗）**

建立 `/tmp/claude-1000/-home-johnny-Desktop-linebot/*/scratchpad/check_geo.mjs`（或任何暫存路徑，此檔**不入版控**）：

```js
import assert from 'node:assert/strict'
import { haversineKm, groupByMajor, RANGES, DEFAULT_RANGE_KM, OTHER }
  from '/home/johnny/Desktop/linebot/frontend/src/geo.js'

// 同一點距離為 0
const 中壢車站 = { lat: 24.9537, lng: 121.2251 }
assert.equal(haversineKm(中壢車站, 中壢車站), 0)

// 中壢車站 → 桃園車站 實際直線約 9.7 km
const 桃園車站 = { lat: 24.9891, lng: 121.3133 }
const d = haversineKm(中壢車站, 桃園車站)
assert.ok(d > 9 && d < 10.5, `中壢→桃園 應約 9.7km，得到 ${d}`)

// 缺座標的店不該被當成 0 公里（那會讓它出現在每個範圍裡）
assert.equal(haversineKm(中壢車站, null), Infinity)
assert.equal(haversineKm(null, 桃園車站), Infinity)

// 檔位：五檔、由小到大、含預設值
assert.equal(RANGES.length, 5)
assert.deepEqual(RANGES.map((r) => r.km), [1, 3, 5, 10, 30])
assert.deepEqual(RANGES.map((r) => r.minutes), [5, 10, 15, 20, 40])
assert.ok(RANGES.some((r) => r.km === DEFAULT_RANGE_KM))

// 分組：家數多的在前，未分類歸「其他」且永遠墊底
const groups = groupByMajor([
  { cuisine_major: '日式' }, { cuisine_major: null }, { cuisine_major: '台式' },
  { cuisine_major: '日式' }, { cuisine_major: '' }, { cuisine_major: '日式' },
])
assert.deepEqual(groups, [
  { major: '日式', count: 3 },
  { major: '台式', count: 1 },
  { major: OTHER, count: 2 },
])
assert.deepEqual(groupByMajor([]), [])

console.log('✅ geo.js 全部通過')
```

- [ ] **Step 2: 跑一次確認失敗**

Run: `node <scratchpad>/check_geo.mjs`
Expected: FAIL — `ERR_MODULE_NOT_FOUND: Cannot find module '.../frontend/src/geo.js'`

- [ ] **Step 3: 寫最小實作**

Create `frontend/src/geo.js`:

```js
// 距離/分組純函式 + 範圍常數。無 I/O、無 React —— 可以用 node 直接跑。
//
// 車程分鐘是**手工校準的常數表，不是公式**：短程走市區、長程走國道，
// 均速差兩倍以上，線性公式套不住。km×3 會把 30km 算成 90 分（實際約 40 分），
// 使用者看到就永遠不會按那一檔，等於白做。只有五檔，查表比公式誠實也準確。
export const RANGES = [
  { km: 1, label: '1 km', minutes: 5 },    // 含紅綠燈與停車
  { km: 3, label: '3 km', minutes: 10 },   // 中壢區內
  { km: 5, label: '5 km', minutes: 15 },
  { km: 10, label: '10 km', minutes: 20 }, // 中壢→桃園市區
  { km: 30, label: '30 km', minutes: 40 }, // 中壢→竹北約 30 分、→台北約 50 分
]

export const DEFAULT_RANGE_KM = 5

// 沒有大類的店歸這裡，才不會在「附近有什麼」裡憑空消失
export const OTHER = '其他'

const EARTH_R_KM = 6371

export function haversineKm(a, b) {
  // 缺座標回 Infinity 而不是 0 —— 回 0 會讓它出現在每一個範圍裡
  if (!a || !b || a.lat == null || a.lng == null || b.lat == null || b.lng == null) {
    return Infinity
  }
  const toRad = (deg) => (deg * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_R_KM * Math.asin(Math.sqrt(h))
}

// 依大類分組計數。家數多的排前面（決策資訊：1 家的日式跟 6 家的日式不一樣），
// 同數量時用名稱排以求穩定；「其他」永遠墊底。
export function groupByMajor(places) {
  const counts = new Map()
  for (const p of places) {
    const key = p.cuisine_major || OTHER
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([major, count]) => ({ major, count }))
    .sort((x, y) => {
      if (x.major === OTHER) return 1
      if (y.major === OTHER) return -1
      return y.count - x.count || x.major.localeCompare(y.major)
    })
}
```

- [ ] **Step 4: 跑一次確認通過**

Run: `node <scratchpad>/check_geo.mjs`
Expected: PASS — 印出 `✅ geo.js 全部通過`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/geo.js
git commit -m "feat(food): geo.js——距離計算與大類分組純函式

車程分鐘用手工校準常數表而非公式：短程市區、長程國道均速差兩倍，
km×3 會把 30km 算成 90 分（實際約 40 分）→ 那一檔就沒人會按。
缺座標回 Infinity 不回 0，否則沒座標的店會出現在每個範圍裡。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `Nearby.jsx` + 樣式 + 接進 `Food.jsx`

**Files:**
- Create: `frontend/src/Nearby.jsx`
- Modify: `frontend/src/Food.jsx`（整支重寫，見下方完整程式碼）
- Modify: `frontend/src/index.css`（在 `.food-error` 規則後追加）

**Interfaces:**
- Consumes: Task 1 的 `RANGES`、`DEFAULT_RANGE_KM`、`OTHER`、`haversineKm`、`groupByMajor`；既有 `frontend/src/cuisine.js` 的 `MAJOR_ICON`、`MAJORS`
- Produces: `<Nearby groups total rangeKm onRangeChange major onMajorChange onRelocate />` 純呈現元件

- [ ] **Step 1: 建立 `Nearby.jsx`**

```jsx
import { RANGES } from './geo'
import { MAJOR_ICON } from './cuisine'

// 純呈現：收「已經算好的分組結果」+ 目前範圍，畫滑桿與磚塊。
// 不自己定位、不自己抓資料、不自己算距離 —— 跟 FoodList/FoodMap 同樣的分工，
// 所有狀態都住在 Food.jsx。
export default function Nearby({
  groups, total, rangeKm, onRangeChange, major, onMajorChange, onRelocate,
}) {
  const idx = Math.max(0, RANGES.findIndex((r) => r.km === rangeKm))
  const range = RANGES[idx]
  const next = RANGES[idx + 1]

  return (
    <div className="nearby">
      <div className="range-row">
        <input
          className="range-slider"
          type="range"
          min="0"
          max={RANGES.length - 1}
          step="1"
          value={idx}
          aria-label="範圍"
          onChange={(e) => onRangeChange(RANGES[Number(e.target.value)].km)}
        />
        <button className="icon-btn" onClick={onRelocate} title="重新定位">📍</button>
      </div>
      <div className="range-caption">
        {range.label} 內 · 約 {range.minutes} 分車程 · 共 {total} 家
      </div>

      {total === 0 ? (
        <div className="list-empty">
          <div>{range.label} 內沒有店家</div>
          {next && (
            <button className="chip" onClick={() => onRangeChange(next.km)}>
              拉大到 {next.label}
            </button>
          )}
        </div>
      ) : (
        <div className="tile-grid">
          {groups.map((g) => (
            <button
              key={g.major}
              className={g.major === major ? 'tile active' : 'tile'}
              onClick={() => onMajorChange(g.major === major ? 'all' : g.major)}
            >
              <span className="tile-icon">{MAJOR_ICON[g.major] || '🍽️'}</span>
              <span className="tile-name">{g.major}</span>
              <span className="tile-count">{g.count} 家</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 重寫 `Food.jsx`**

整支替換成：

```jsx
import { useEffect, useState } from 'react'
import { getPlaces } from './api'
import { MAJORS } from './cuisine'
import { RANGES, DEFAULT_RANGE_KM, OTHER, haversineKm, groupByMajor } from './geo'
import FoodList from './FoodList.jsx'
import FoodMap from './FoodMap.jsx'
import Nearby from './Nearby.jsx'
import PlaceSheet from './PlaceSheet.jsx'

const STATUS = [
  { key: 'all', label: '全部' },
  { key: '想去', label: '想去' },
  { key: '去過', label: '去過' },
]

// 三態循環；按鈕顯示的是「下一個模式」的圖示（沿用原本清單模式長 🗺️ 的慣例）
const NEXT_VIEW = { nearby: 'list', list: 'map', map: 'nearby' }
const NEXT_ICON = { nearby: '☰', list: '🗺️', map: '📍' }

// 「資料的唯一主人」：所有店家、篩選、定位、選中誰都放這裡（lifting state up）。
// Nearby / FoodList / FoodMap 只是三種「畫法」，收 props、把互動回報上來。
export default function Food() {
  const [places, setPlaces] = useState([])
  const [status, setStatus] = useState('all')
  const [city, setCity] = useState('all')
  const [district, setDistrict] = useState('all')
  const [major, setMajor] = useState('all')
  const [view, setView] = useState('nearby')      // 'nearby' | 'list' | 'map'
  const [coords, setCoords] = useState(null)
  const [rangeKm, setRangeKm] = useState(DEFAULT_RANGE_KM)
  const [geoState, setGeoState] = useState('locating')  // locating | ready | denied
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getPlaces()
      .then((data) => setPlaces(data.places || []))
      .catch((e) => setError(String(e.message || e)))
  }, [])

  // 定位失敗一律**自動退回清單**，不彈窗擋路 —— 使用者永遠看得到自己的清單。
  // 這是把「附近」當預設畫面的唯一代價，必須設計掉。
  function locate() {
    if (!navigator.geolocation) {
      setGeoState('denied')
      setView('list')
      return
    }
    setGeoState('locating')
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude })
        setGeoState('ready')
      },
      () => {
        setGeoState('denied')
        setView('list')
      },
      { enableHighAccuracy: false, timeout: 6000, maximumAge: 300000 },
    )
  }

  useEffect(() => { locate() }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  // 寫操作（去過/照片）完成後重抓，並讓打開中的詳情面板同步顯示新狀態
  async function reload(keepSelectedId) {
    try {
      const data = await getPlaces()
      const fresh = data.places || []
      setPlaces(fresh)
      if (keepSelectedId != null) {
        setSelected(fresh.find((p) => p.id === keepSelectedId) || null)
      }
    } catch (e) {
      setError(String(e.message || e))
    }
  }

  // 選項一律從資料長出來，不寫死 —— 沒有店家的縣市/分類不該出現在選單裡
  const cities = [...new Set(places.map((p) => p.city).filter(Boolean))].sort()
  const districts =
    city === 'all'
      ? []
      : [...new Set(
          places.filter((p) => p.city === city).map((p) => p.district).filter(Boolean),
        )].sort()
  const present = new Set(places.map((p) => p.cuisine_major).filter(Boolean))
  const majors = MAJORS.filter((m) => present.has(m))

  // 換縣市一定要把行政區歸零：否則選了「中壢區」再切到台北市，
  // 清單會永遠空白，而且畫面上看不出原因。
  function changeCity(next) {
    setCity(next)
    setDistrict('all')
  }

  function cycleView() {
    const next = NEXT_VIEW[view]
    setView(next)
    if (next === 'nearby' && !coords) locate()
  }

  // 篩選鏈：狀態 → 範圍（附近模式）或縣市/行政區（清單/地圖模式）→ 料理大類。
  // 附近模式不套縣市/行政區：範圍已經由距離決定，兩套地區篩選並存只會打架。
  const byStatus = places.filter((p) => status === 'all' || p.status === status)
  const nearby = coords ? byStatus.filter((p) => haversineKm(coords, p) <= rangeKm) : []
  const scoped =
    view === 'nearby'
      ? nearby
      : byStatus.filter(
          (p) => (city === 'all' || p.city === city) && (district === 'all' || p.district === district),
        )
  const groups = groupByMajor(nearby)
  const shown = scoped.filter((p) => major === 'all' || (p.cuisine_major || OTHER) === major)

  function rollDice() {
    if (!shown.length) return
    setSelected(shown[Math.floor(Math.random() * shown.length)])
  }

  return (
    <div className="food">
      <div className="food-bar">
        <div className="chips">
          {STATUS.map((s) => (
            <button
              key={s.key}
              className={s.key === status ? 'chip active' : 'chip'}
              onClick={() => setStatus(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="bar-right">
          <button className="icon-btn" onClick={rollDice} title="抽一家">🎲</button>
          <button className="icon-btn" onClick={cycleView} title="切換 附近 / 清單 / 地圖">
            {NEXT_ICON[view]}
          </button>
        </div>
      </div>

      {/* 第二列：地區（縣市→行政區級聯）+ 料理大類。附近模式不顯示地區選單。 */}
      <div className="food-bar2">
        {view !== 'nearby' && (
          <>
            <select className="city-select" value={city} onChange={(e) => changeCity(e.target.value)}>
              <option value="all">全部縣市</option>
              {cities.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            {districts.length > 0 && (
              <select
                className="city-select"
                value={district}
                onChange={(e) => setDistrict(e.target.value)}
              >
                <option value="all">全部地區</option>
                {districts.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            )}
          </>
        )}
        {majors.length > 0 && (
          <>
            {view !== 'nearby' && <span className="bar-divider" />}
            <button
              className={major === 'all' ? 'chip active' : 'chip'}
              onClick={() => setMajor('all')}
            >
              全部
            </button>
            {majors.map((m) => (
              <button
                key={m}
                className={m === major ? 'chip active' : 'chip'}
                onClick={() => setMajor(m === major ? 'all' : m)}
              >
                {m}
              </button>
            ))}
          </>
        )}
      </div>

      {geoState === 'denied' && (
        <div className="geo-banner">
          沒有定位權限，顯示全部店家
          <button className="chip" onClick={locate}>重試</button>
        </div>
      )}
      {error && <div className="food-error">{error}</div>}

      {view === 'nearby' ? (
        geoState === 'locating' ? (
          <div className="list-empty">正在定位…</div>
        ) : (
          <div className="nearby-scroll">
            <Nearby
              groups={groups}
              total={nearby.length}
              rangeKm={rangeKm}
              onRangeChange={setRangeKm}
              major={major}
              onMajorChange={setMajor}
              onRelocate={locate}
            />
            {/* 選了料理才列店 —— 決策流程是「範圍 → 料理 → 店」，
                沒選之前磚塊本身就是答案，畫面保持乾淨。 */}
            {major !== 'all' && <FoodList places={shown} onSelect={setSelected} />}
          </div>
        )
      ) : view === 'list' ? (
        <FoodList places={shown} onSelect={setSelected} />
      ) : (
        <FoodMap places={shown} selected={selected} onSelect={setSelected} />
      )}

      <PlaceSheet place={selected} onClose={() => setSelected(null)} onChanged={reload} />
    </div>
  )
}
```

- [ ] **Step 3: 追加樣式**

在 `frontend/src/index.css` 的 `.food-error { ... }` 規則**之後**插入：

```css
/* ── 附近：範圍滑桿 + 料理磚塊 ── */
.geo-banner {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 6px 12px; background: #fff8e1; color: #8a6d3b; font-size: 0.85rem;
}
/* 磚塊與卡片同屬一個捲動容器：兩個都要 flex:1 會互搶高度，
   所以由外層負責捲動，內層清單取消自己的捲動。 */
.nearby-scroll { flex: 1; min-height: 0; overflow-y: auto; }
.nearby-scroll .food-list { flex: none; overflow: visible; }
.nearby { padding: 12px; }
.range-row { display: flex; align-items: center; gap: 10px; }
.range-slider { flex: 1; accent-color: var(--brand); }
.range-caption { margin: 8px 2px 14px; font-size: 0.85rem; color: #777; }
.tile-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 10px;
}
.tile {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  background: #fff; border: 1px solid #eee; border-radius: 14px;
  padding: 14px 8px; cursor: pointer;
}
.tile.active { border-color: var(--brand); background: #fff7f0; }
.tile-icon { font-size: 1.6rem; }
.tile-name { font-size: 0.9rem; color: #333; }
.tile-count { font-size: 0.8rem; color: #999; }
```

- [ ] **Step 4: Build**

Run: `npm run build --prefix frontend`
Expected: `✓ built in ...`，無錯誤。若出現 `"Nearby" is not exported` 之類，代表 import 路徑打錯。

- [ ] **Step 5: Playwright 驗磚塊（灌中壢座標）**

把下列腳本寫到暫存檔後 `docker cp` 進容器再執行：

```python
import asyncio, sys
sys.path.insert(0, '/app')
from playwright.async_api import async_playwright
from database import SessionLocal
from models import DeviceToken

s = SessionLocal(); t = s.query(DeviceToken).order_by(DeviceToken.id.desc()).first(); s.close()
CHUNGLI = {"latitude": 24.9537, "longitude": 121.2251}

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=2,
            is_mobile=True, has_touch=True,
            geolocation=CHUNGLI, permissions=["geolocation"],
        )
        await ctx.add_init_script(f"localStorage.setItem('deviceToken', {t.token!r})")
        page = await ctx.new_page()
        await page.goto("http://127.0.0.1:8000/m/", wait_until="networkidle")
        await page.wait_for_timeout(2500)
        cap = await page.locator(".range-caption").inner_text()
        print("caption:", cap)
        tiles = page.locator(".tile")
        n = await tiles.count()
        total = 0
        for i in range(n):
            txt = (await tiles.nth(i).inner_text()).replace("\n", " ")
            total += int(txt.split()[-1].replace("家", ""))
            print("  tile:", txt)
        print("磚塊家數合計 =", total)
        await page.screenshot(path="/tmp/nearby.png")
        # 拉到 30km 檔，家數必須增加
        await page.locator(".range-slider").fill("4")
        await page.wait_for_timeout(500)
        print("30km caption:", await page.locator(".range-caption").inner_text())
        await page.screenshot(path="/tmp/nearby_30.png")
        await b.close()

asyncio.run(main())
```

Expected:
- caption 形如 `5 km 內 · 約 15 分車程 · 共 N 家`
- **磚塊家數合計 == caption 的 N**（分組沒有漏算或重複算）
- 拉到 30km 後 N 明顯變大
- 截圖 `/tmp/nearby.png` 拉回 host 目視：磚塊排版正常、tab bar 沒被頂走

- [ ] **Step 6: Python 交叉驗算距離**

JS 的 haversine 要跟獨立實作對得起來，否則家數看起來合理但其實是錯的：

```bash
docker exec -w /app money-bot python -c "
from math import radians, sin, cos, asin, sqrt
from food.repo import list_places
def hav(a, b):
    dlat, dlng = radians(b[0]-a[0]), radians(b[1]-a[1])
    h = sin(dlat/2)**2 + cos(radians(a[0]))*cos(radians(b[0]))*sin(dlng/2)**2
    return 2*6371*asin(sqrt(h))
me = (24.9537, 121.2251)
for km in (5, 30):
    n = sum(1 for p in list_places()
            if p['lat'] and p['lng'] and hav(me, (p['lat'], p['lng'])) <= km)
    print(f'{km}km 內應有 {n} 家')
"
```

Expected: 印出的數字**與 Step 5 caption 的 N 完全相同**（狀態篩選預設是「全部」，所以兩邊母體一致）。不同就是 JS haversine 寫錯了。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/Nearby.jsx frontend/src/Food.jsx frontend/src/index.css
git commit -m "feat(food): 附近模式——範圍滑桿 + 帶家數的料理磚塊

回答 Google Maps 不回答的問題：這附近有哪些選擇（而且是已篩選過的）。
磚塊上的家數是決策資訊——1 家的日式跟 6 家的日式不一樣。
附近模式隱藏縣市/行政區選單：範圍已由距離決定，兩套地區篩選並存會打架。
選了料理才列店，沒選之前磚塊本身就是答案。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 定位失敗的退路

**Files:**
- Test: 無新增檔案（Playwright 腳本走暫存路徑）

**Interfaces:**
- Consumes: Task 2 的 `locate()` / `geoState` / `NEXT_VIEW`
- Produces: 無新介面 —— 這個 task 只驗行為，程式碼在 Task 2 已寫入

> **注意**：退路的實作（`setGeoState('denied')` + `setView('list')` + banner）已經包含在 Task 2 的 `Food.jsx` 裡。這個 task 存在的理由是它是**整個設計的頭號風險**（把「附近」當預設畫面，沒給權限就可能卡死首屏），必須獨立驗證、獨立被 review，不能跟功能驗證混在一起矇混過去。

- [ ] **Step 1: 寫「不給權限」的 Playwright 腳本**

與 Task 2 Step 5 相同，但 **context 不給 `permissions` 也不給 `geolocation`**：

```python
import asyncio, sys
sys.path.insert(0, '/app')
from playwright.async_api import async_playwright
from database import SessionLocal
from models import DeviceToken

s = SessionLocal(); t = s.query(DeviceToken).order_by(DeviceToken.id.desc()).first(); s.close()

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(              # ← 刻意不給 geolocation / permissions
            viewport={"width": 390, "height": 844}, device_scale_factor=2,
            is_mobile=True, has_touch=True,
        )
        await ctx.add_init_script(f"localStorage.setItem('deviceToken', {t.token!r})")
        page = await ctx.new_page()
        await page.goto("http://127.0.0.1:8000/m/", wait_until="networkidle")
        await page.wait_for_timeout(9000)       # 撐過 6 秒 timeout
        print("卡在定位中？", await page.locator(".list-empty").count() and
              "正在定位" in (await page.locator(".list-empty").inner_text()))
        print("banner:", await page.locator(".geo-banner").count())
        print("卡片數:", await page.locator(".card").count())
        print("磚塊數:", await page.locator(".tile").count())
        await page.screenshot(path="/tmp/nearby_denied.png")
        await b.close()

asyncio.run(main())
```

- [ ] **Step 2: 執行並確認退路成立**

Run: `docker cp <腳本> money-bot:/tmp/ && docker exec money-bot python /tmp/<腳本>`

Expected（四項全部要成立，缺一就是退路壞了）：
- `卡在定位中？ False` —— 沒有停在「正在定位…」
- `banner: 1` —— 有那條說明用的細 banner
- `卡片數: > 0` —— **已經自動退回清單，使用者看得到自己的清單**
- `磚塊數: 0` —— 沒有停留在附近模式

- [ ] **Step 3: 截圖目視**

Run: `docker cp money-bot:/tmp/nearby_denied.png /tmp/ ` 後開來看
Expected: 頂端一條淡黃 banner + 底下正常的店家卡片清單，版面沒有破。

- [ ] **Step 4: Commit（若 Step 2 有任何一項不成立才會有程式碼改動）**

若四項全過 → 沒有程式碼要改，跳過 commit，在 review 註記「退路已驗證」。
若不成立 → 修 `Food.jsx` 的 `locate()` 錯誤分支後：

```bash
git add frontend/src/Food.jsx
git commit -m "fix(food): 定位失敗未正確退回清單模式

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 文件與實機確認

**Files:**
- Modify: `README.md`（美食地圖段落，約 L31-41）
- Modify: `CODEBASE.md`（`frontend/` 那一行）

**Interfaces:**
- Consumes: 前三個 task 的成品
- Produces: 無程式介面

> **注意**：`README.md`、`CODEBASE.md`、`main.py`、`discordbot/` 目前可能有**別輪未提交的改動**（Discord 監管式啟動）。**不要**把它們掃進這次的 commit。用 `git diff <file> > /tmp/x.patch` 抽出只屬於本功能的 hunk，再 `git apply --cached` 精準暫存。

- [ ] **Step 1: 更新 README.md**

在美食地圖段落插入一條：

```markdown
- **附近有什麼**（預設畫面）：進美食頁先定位，拉範圍滑桿（1/3/5/10/30 km，標註約略車程），看到**這個範圍內你的清單有哪些料理、各幾家**——Google Maps 只回答「X 在哪裡」，這裡回答「附近有哪些已經被你篩過的選擇」。點料理磚塊才展開店家。沒給定位權限會自動退回清單模式，不會卡住。
```

- [ ] **Step 2: 更新 CODEBASE.md**

把 `frontend/` 那行的美食部分改成（保留該行其餘內容不動）：

```
美食(Food/Nearby/FoodList/FoodMap/PlaceSheet/geo.js/cuisine.js；預設「附近」模式：定位→範圍滑桿(1/3/5/10/30km,車程標註是手工校準常數表不是公式)→料理磚塊帶家數→點磚塊才列店。定位失敗自動退回清單+banner,絕不卡首屏。geo.js 是無 React 純函式,可用 node --input-type=module 直接跑驗。三態切換 附近/清單/地圖,附近模式隱藏縣市選單避免與距離打架)
```

- [ ] **Step 3: 精準暫存並 commit**

```bash
git diff README.md CODEBASE.md > /tmp/docs_full.patch
# 用 python 濾掉含 run_discord_bot / Discord Bot 韌性 的 hunk，其餘寫成 /tmp/docs_mine.patch
git apply --cached /tmp/docs_mine.patch
git diff --cached | grep -c "run_discord_bot"   # 必須是 0
git commit -m "docs(food): 附近有什麼——README + CODEBASE

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: 全套回歸**

```bash
docker exec -w /app money-bot python -m pytest tests/ -q
```
Expected: 426 passed（本功能不改後端，測試數不該變）

- [ ] **Step 5: 確認伺服器送的是新 bundle**

```bash
curl -s -H "ngrok-skip-browser-warning: true" http://127.0.0.1:8000/m/index.html \
  | grep -oE "assets/index-[A-Za-z0-9_-]+\.js"
```
再 curl 那支 bundle，`grep -c "分車程"` 必須 ≥ 1。伺服器端正確 = 之後看不到就是裝置快取問題。

- [ ] **Step 6: 交使用者實機確認（不可跳過、不可代為宣稱完成）**

請使用者在手機上打開 PWA 確認：定位問得出來、滑桿好按、磚塊排版正常、點磚塊會列店。
**PWA 有 service worker 快取，可能要重開 App 1~2 次新版才接管**（AGENTS.md §1 記載的頭號誤判來源）。

---

## Self-Review

**Spec 覆蓋檢查：**

| Spec 要求 | 對應 |
|---|---|
| D1 直線距離不用真實車程 | Task 1 `haversineKm` |
| D2 五檔位 + 手工校準車程表 | Task 1 `RANGES`，Step 1 斷言鎖住 `[1,3,5,10,30]` / `[5,10,15,20,40]` |
| D3 當預設畫面但定位失敗自動退回 | Task 2（`view` 初值 `'nearby'` + `locate()` 錯誤分支）、Task 3 專門驗證 |
| D4 磚塊顯示家數、未分類歸「其他」 | Task 1 `groupByMajor` + `OTHER`，Task 2 磚塊渲染 |
| D5 附近模式隱藏地區選單、想去/去過保留 | Task 2 `{view !== 'nearby' && ...}`；`byStatus` 在所有模式都先套用 |
| 零後端改動 | Global Constraints 明列；Task 4 Step 4 用「測試數不變」驗證 |
| 點磚塊展開、再點取消 | Task 2 `onMajorChange(g.major === major ? 'all' : g.major)` |
| 範圍內 0 家的空狀態 + 跳下一檔 | Task 2 `Nearby.jsx` 的 `total === 0` 分支 |
| 重新定位按鈕 | Task 2 `onRelocate` → `locate()`；banner 的「重試」走同一條 |
| 三態切換顯示下一個模式圖示 | Task 2 `NEXT_ICON` |
| 驗證靠 Playwright + 使用者親眼 | Task 2 Step 5-6、Task 3、Task 4 Step 6 |

無遺漏。

**Placeholder 掃描：** 無 TBD/TODO；所有程式碼步驟都有完整可貼上的內容；Task 3 明確說明「程式碼在 Task 2、本 task 只驗行為」而非含糊帶過。

**型別一致性：** `haversineKm(a, b)` 在 Task 1 定義、Task 2 以 `haversineKm(coords, p)` 呼叫（`p` 本身帶 `lat`/`lng` 屬性，符合簽名）；`groupByMajor` 回傳 `{major, count}` 與 `Nearby.jsx` 的 `g.major` / `g.count` 一致；`OTHER` 在 Task 1 匯出、Task 2 用於 `(p.cuisine_major || OTHER) === major` 與磚塊 key 對得起來；`RANGES` 的 `km`/`label`/`minutes` 三個欄位在 `Nearby.jsx` 全部用到且名稱相符。
