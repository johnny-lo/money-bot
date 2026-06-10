import { useEffect, useState } from 'react'
import { getPlaces } from './api'
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

  // 資料裡實際有哪些縣市（給下拉選單用）
  const cities = [...new Set(places.map((p) => p.city).filter(Boolean))]

  // 套用兩個篩選 → 清單、地圖、骰子全部共用這一份
  const shown = places.filter(
    (p) => (status === 'all' || p.status === status) && (city === 'all' || p.city === city),
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
          <select className="city-select" value={city} onChange={(e) => setCity(e.target.value)}>
            <option value="all">全部縣市</option>
            {cities.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
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
