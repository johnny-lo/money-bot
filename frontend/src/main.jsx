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

// 主動觸發更新檢查 —— 手機缺的就是這一環。
// 瀏覽器只在「導覽發生」時才去比對 sw.js。桌機按重新整理就算一次；但主畫面 App
// 沒有重整鈕，iOS 又是暫停而非終止，從 App 切換器切回來常常不算導覽 → 檢查永遠
// 不觸發，controllerchange 也就永遠等不到，於是一直卡舊版。
// 這裡改成「回到前景就問一次」，把「重開 App」變成真的有效的動作。
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.ready.then((reg) => {
    const check = () => {
      if (document.visibilityState === 'visible') reg.update().catch(() => {})
    }
    document.addEventListener('visibilitychange', check)
    window.addEventListener('focus', check)
    setInterval(check, 30 * 60 * 1000)   // 長開不關的情況
    check()
  }).catch(() => {})
}
