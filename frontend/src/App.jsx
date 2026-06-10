import { useState } from 'react'
import Food from './Food.jsx'
import Spend from './Spend.jsx'

// 底部三個分頁。先用陣列定義，下面用 .map() 一次畫出來。
const TABS = [
  { key: 'map', icon: '🍜', label: '美食' },
  { key: 'spend', icon: '💰', label: '消費' },
  { key: 'recipe', icon: '🍳', label: '食譜' },
]

export default function App() {
  // useState：宣告一塊「會變、且一變畫面就跟著重畫」的狀態。
  // tab = 現在選哪個分頁；setTab = 改它的唯一方法。預設 'map'。
  const [tab, setTab] = useState('map')

  return (
    <div className="app">
      {/* 主畫面：依 tab 決定顯示哪一頁。先放佔位，功能之後接。 */}
      <main className="screen">
        {tab === 'map' && <Food />}
        {tab === 'spend' && <Spend />}
        {tab === 'recipe' && <div className="placeholder">🍳 食譜（之後做）</div>}
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
    </div>
  )
}
