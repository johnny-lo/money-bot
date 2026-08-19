import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Vite = 開發伺服器 + 打包器。
export default defineConfig({
  // 部署時 FastAPI 把這個 app serve 在 https://<ngrok>/m/ 底下
  base: '/m/',

  // 版本戳：build 當下的時間，直接編進 bundle 並顯示在畫面右下角。
  // 為什麼要有：這個 app 的頭號疑難雜症是「改了手機上看不到」，而過去只能靠
  // curl 伺服器 + 猜裝置端快取。有這個戳記，使用者看一眼就知道手上是不是新版。
  define: {
    __BUILD_ID__: JSON.stringify(
      new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Taipei' }).slice(5, 16),
    ),
  },
  plugins: [
    react(),   // 讓 Vite 看得懂 JSX / React

    // PWA = manifest（讓手機知道「這是個可安裝的 app」）+ service worker（離線快取）。
    // 這個 plugin 在 build 時自動：產 manifest.webmanifest、產 sw.js（用 Workbox）、
    // 在 index.html 注入 <link rel="manifest"> 和 SW 註冊碼。
    VitePWA({
      // autoUpdate：偵測到新版 build 就背景更新，下次開啟生效（另一選項 prompt = 跳「有新版」讓使用者按）
      registerType: 'autoUpdate',
      // injectManifest：SW 改用我們自己寫的 src/sw.js（generateSW 的 schema 不給加自訂
      // fetch header，而 /media 需要帶 ngrok 跳過攔截頁的 header —— 詳見 src/sw.js）
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.js',
      // public/ 裡不在 manifest icons 清單、但也要進 precache 的檔案
      includeAssets: ['apple-touch-icon.png'],
      manifest: {
        name: '生活',
        short_name: '生活',
        description: '美食地圖・消費・食譜',
        lang: 'zh-TW',
        // start_url/scope 都鎖在 /m/：SW 檔案放在 /m/sw.js，瀏覽器規定 SW 管轄範圍
        // 最大只能到它所在的路徑 → 不會誤管到 /report 或 /api
        start_url: '/m/',
        scope: '/m/',
        display: 'standalone',          // 全螢幕、無瀏覽器網址列 → 像原生 app
        theme_color: '#E67E22',         // 狀態列配色（跟 index.html 的 meta 一致）
        background_color: '#f5f5f5',    // 開屏 splash 底色（跟 body 背景一致才不會閃色）
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
          // maskable：Android 會把 icon 裁成圓形/圓角方形等，這張是「允許被裁」的版本
          //（我們的設計是滿版橘底+置中字，裁什麼形狀都安全）
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      // 快取策略（precache / API NetworkFirst / media CacheFirst+header）全在 src/sw.js
    }),
  ],
  server: {
    // 開發時 React 跑在 :5173,後端 FastAPI 在 :8000。
    // 這行讓前端打 /api/... 時自動轉給後端 → 開發期就不用煩 CORS。
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',   // npm run build 會把成品吐到 frontend/dist/，之後交給 FastAPI serve
  },
})
