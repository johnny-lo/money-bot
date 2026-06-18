import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// 整個 app 的進入點：把 <App /> 這棵元件樹，掛到 index.html 裡那個 #root。
createRoot(document.getElementById('root')).render(<App />)

// PWA 新版自動套用：新 service worker 接管（skipWaiting+clientsClaim 後）時，
// 自動重整一次，讓使用者免手動關開兩次清快取。
// 只有「載入時已被舊 SW 控制」才掛 → 首次安裝(無 controller)不會多閃一次；
// refreshing 旗標防止重整迴圈。
if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
  let refreshing = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return
    refreshing = true
    window.location.reload()
  })
}
