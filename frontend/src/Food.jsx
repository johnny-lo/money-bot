import { useEffect, useState } from 'react'
import { getPlaces } from './api'
import { MAJORS } from './cuisine'
import FoodList from './FoodList.jsx'
import FoodMap from './FoodMap.jsx'
import PlaceSheet from './PlaceSheet.jsx'

const STATUS = [
  { key: 'all', label: '全部' },
  { key: '想去', label: '想去' },
  { key: '去過', label: '去過' },
]

// 「資料的唯一主人」：所有店家、篩選、選中誰都放這裡（lifting state up）。
// FoodList / FoodMap 只是兩種「畫法」，收 props、把點擊回報上來。
export default function Food() {
  const [places, setPlaces] = useState([])
  const [status, setStatus] = useState('all')
  const [city, setCity] = useState('all')
  const [district, setDistrict] = useState('all')
  const [major, setMajor] = useState('all')
  const [view, setView] = useState('list') // 'list' | 'map'
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getPlaces()
      .then((data) => setPlaces(data.places || []))
      .catch((e) => setError(String(e.message || e)))
  }, [])

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
  // 大類照固定順序排，但只留資料裡真的有的（不出現永遠 0 筆的死 chip）
  const present = new Set(places.map((p) => p.cuisine_major).filter(Boolean))
  const majors = MAJORS.filter((m) => present.has(m))

  // 換縣市一定要把行政區歸零：否則選了「中壢區」再切到台北市，
  // 清單會永遠空白，而且畫面上看不出原因。
  function changeCity(next) {
    setCity(next)
    setDistrict('all')
  }

  // 套用四個篩選 → 清單、地圖、骰子全部共用這一份
  const shown = places.filter(
    (p) =>
      (status === 'all' || p.status === status) &&
      (city === 'all' || p.city === city) &&
      (district === 'all' || p.district === district) &&
      (major === 'all' || p.cuisine_major === major),
  )

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
          <button
            className="icon-btn"
            onClick={() => setView(view === 'list' ? 'map' : 'list')}
            title="切換清單 / 地圖"
          >
            {view === 'list' ? '🗺️' : '☰'}
          </button>
        </div>
      </div>

      {/* 第二列：地區（縣市 → 行政區級聯）+ 料理大類。12 個 chip 塞不下一行 → 橫向可捲 */}
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

      {error && <div className="food-error">{error}</div>}

      {view === 'list' ? (
        <FoodList places={shown} onSelect={setSelected} />
      ) : (
        <FoodMap places={shown} selected={selected} onSelect={setSelected} />
      )}

      <PlaceSheet place={selected} onClose={() => setSelected(null)} onChanged={reload} />
    </div>
  )
}
