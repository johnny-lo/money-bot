import { useEffect, useState } from 'react'
import Food from './Food.jsx'
import Spend from './Spend.jsx'
import Recipe from './Recipe.jsx'
import Videos from './Videos.jsx'
import { currentBundle, fetchServerBundle, forceUpdate, isStale } from './update.js'

// 底部分頁。先用陣列定義，下面用 .map() 一次畫出來。
const TABS = [
  { key: 'map', icon: '🍜', label: '美食' },
  { key: 'spend', icon: '💰', label: '消費' },
  { key: 'recipe', icon: '🍳', label: '食譜' },
  { key: 'video', icon: '🎥', label: '歷史' },
]

export default function App() {
  // useState：宣告一塊「會變、且一變畫面就跟著重畫」的狀態。
  // tab = 現在選哪個分頁；setTab = 改它的唯一方法。預設 'map'。
  const [tab, setTab] = useState('map')

  // 落後偵測：直接問伺服器「殼現在指向哪個 bundle」，跟手上這份比。
  // 刻意不依賴 SW 的更新機制 —— 卡住的時候正好就是那套機制沒動作，
  // 靠它自己回報等於請當事人自首。抓不到（離線）就當作沒事，寧可漏報不要誤報。
  const [stale, setStale] = useState(false)
  useEffect(() => {
    const mine = currentBundle()
    const check = async () => {
      if (document.visibilityState !== 'visible') return
      try { setStale(isStale(mine, await fetchServerBundle())) } catch { /* 離線 */ }
    }
    check()
    document.addEventListener('visibilitychange', check)
    const id = setInterval(check, 5 * 60 * 1000)
    return () => { document.removeEventListener('visibilitychange', check); clearInterval(id) }
  }, [])

  return (
    <div className="app">
      {/* 主畫面：依 tab 決定顯示哪一頁。先放佔位，功能之後接。 */}
      <main className="screen">
        {tab === 'map' && <Food />}
        {tab === 'spend' && <Spend />}
        {tab === 'recipe' && <Recipe />}
        {tab === 'video' && <Videos />}
      </main>

      {/* 底部分頁列：拇指區。用 .map() 把 TABS 畫成三顆按鈕。 */}
      <nav className="tabbar">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={t.key === tab ? 'tab active' : 'tab'}
            onClick={() => setTab(t.key)}
          >
            <span className="tab-icon">{t.icon}</span>
            <span className="tab-label">{t.label}</span>
          </button>
        ))}
      </nav>

      {/* 有新版時的更新條。主畫面 App 沒有網址列也沒有重新整理鈕，
          這顆按鈕就是手機唯一缺的那個逃生口。 */}
      {stale && (
        <button className="update-bar" onClick={forceUpdate}>
          ✨ 有新版可用 · 點一下更新
        </button>
      )}

      {/* 版本戳（build 時間）。「手機是不是還是舊版」看這裡，不用再猜。 */}
      <div className="build-stamp">{__BUILD_ID__}</div>
    </div>
  )
}
