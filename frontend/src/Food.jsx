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
  const [view, setView] = useState('nearby')            // 'nearby' | 'list' | 'map'
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

      {/* 第二列：地區（縣市→行政區級聯）+ 料理大類。
          附近模式整排不顯示 —— 範圍由滑桿決定、料理由磚塊決定，
          再擺一套篩選器只會跟它們打架，而且 chips 比磚塊差（沒家數、
          還列出附近根本沒有的類別）。 */}
      {view !== 'nearby' && (
        <div className="food-bar2">
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
