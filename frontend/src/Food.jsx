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

// 三種畫法用分段控制列出來，而不是一顆循環鈕。
// 為什麼改：循環鈕顯示的是「下一個模式」的圖示，使用者看不出**自己在哪個模式**，
// 而地區/行政區篩選只在清單、地圖模式渲染 → 開 App 停在預設的「附近」時，
// 使用者會以為行政區功能不見了（實際被回報過兩次）。
// 一個控制項＝一個真相來源：三個都列出來、目前的高亮，就沒有猜的空間。
const VIEWS = [
  { key: 'nearby', icon: '📍', label: '附近' },
  { key: 'list', icon: '☰', label: '清單' },
  { key: 'map', icon: '🗺️', label: '地圖' },
]

// 「資料的唯一主人」：所有店家、篩選、定位、選中誰都放這裡（lifting state up）。
// Nearby / FoodList / FoodMap 只是三種「畫法」，收 props、把互動回報上來。
export default function Food() {
  const [places, setPlaces] = useState([])
  const [status, setStatus] = useState('all')
  const [city, setCity] = useState('all')
  const [district, setDistrict] = useState('all')
  const [major, setMajor] = useState('all')
  const [view, setView] = useState('nearby')            // 'nearby' | 'list' | 'map'
  const [coords, setCoords] = useState(null)
  const [rangeKm, setRangeKm] = useState(DEFAULT_RANGE_KM)
  const [geoState, setGeoState] = useState('locating')  // locating | ready | denied
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')
  // 分辨「還沒載完」與「載完了但真的是空的」——沒有這個旗標，
  // 定位比 API 先回來時會閃一下「範圍內沒有店家」，叫使用者去拉大範圍。
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    getPlaces()
      .then((data) => setPlaces(data.places || []))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoaded(true))
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
        // 拿到定位就切去附近 —— 按 banner 的「重試」唯一的動機就是想看附近，
        // 成功了卻停在清單會讓人以為沒反應。（其他呼叫點本來就在附近模式，無副作用）
        setView('nearby')
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

  // 選項一律從資料長出來，不寫死 —— 沒有店家的縣市/分類不該出現在選單裡。
  // 縣市 → 該縣市有店的行政區，給下面的分組選單用。
  const byCity = new Map()
  for (const p of places) {
    if (!p.city) continue
    if (!byCity.has(p.city)) byCity.set(p.city, new Set())
    if (p.district) byCity.get(p.city).add(p.district)
  }
  const cities = [...byCity.keys()].sort()

  const present = new Set(places.map((p) => p.cuisine_major).filter(Boolean))
  const majors = MAJORS.filter((m) => present.has(m))

  // 地區用**一個**分組選單而不是「縣市 + 行政區」兩個級聯選單。
  // 兩個的話行政區被兩道關卡擋著（要先選縣市才會被渲染出來），使用者
  // 根本找不到；而且還要處理「換縣市忘了重置行政區」那類 bug。
  // 一個控制項＝一個真相來源，那整類問題直接消失。
  const regionValue = district !== 'all' ? `d:${city}:${district}` : city !== 'all' ? `c:${city}` : 'all'
  function changeRegion(raw) {
    if (raw === 'all') {
      setCity('all')
      setDistrict('all')
      return
    }
    const [kind, c, d] = raw.split(':')
    setCity(c)
    setDistrict(kind === 'd' ? d : 'all')
  }

  function switchView(next) {
    if (next === view) return
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
          <div className="view-seg" role="tablist" aria-label="檢視模式">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                role="tab"
                aria-selected={v.key === view}
                className={v.key === view ? 'view-seg-btn active' : 'view-seg-btn'}
                onClick={() => switchView(v.key)}
              >
                {v.icon}<span className="view-seg-label">{v.label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 第二列：地區（縣市→行政區級聯）+ 料理大類。
          附近模式整排不顯示 —— 範圍由滑桿決定、料理由磚塊決定，
          再擺一套篩選器只會跟它們打架，而且 chips 比磚塊差（沒家數、
          還列出附近根本沒有的類別）。 */}
      {view === 'nearby' && (
        <div className="view-hint">想按縣市／行政區找？切到「清單」或「地圖」</div>
      )}

      {view !== 'nearby' && (
        <div className="food-bar2">
          <select
            className="city-select region-select"
            value={regionValue}
            onChange={(e) => changeRegion(e.target.value)}
          >
            <option value="all">全部地區</option>
            {cities.map((c) => (
              <optgroup key={c} label={c}>
                <option value={`c:${c}`}>{c} 全部</option>
                {[...byCity.get(c)].sort().map((d) => (
                  <option key={d} value={`d:${c}:${d}`}>{d}</option>
                ))}
              </optgroup>
            ))}
          </select>
          {majors.length > 0 && (
            <>
              <span className="bar-divider" />
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
      )}

      {geoState === 'denied' && (
        <div className="geo-banner">
          沒有定位權限，顯示全部店家
          <button className="chip" onClick={locate}>重試</button>
        </div>
      )}
      {error && <div className="food-error">{error}</div>}

      {view === 'nearby' ? (
        geoState === 'locating' || !loaded ? (
          <div className="list-empty">{loaded ? '正在定位…' : '載入中…'}</div>
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
