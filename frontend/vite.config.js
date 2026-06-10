import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Vite = 開發伺服器 + 打包器。
export default defineConfig({
  // 部署時 FastAPI 把這個 app serve 在 https://<ngrok>/m/ 底下
  base: '/m/',
  plugins: [
    react(),   // 讓 Vite 看得懂 JSX / React

    // PWA = manifest（讓手機知道「這是個可安裝的 app」）+ service worker（離線快取）。
    // 這個 plugin 在 build 時自動：產 manifest.webmanifest、產 sw.js（用 Workbox）、
    // 在 index.html 注入 <link rel="manifest"> 和 SW 註冊碼。
    VitePWA({
      // autoUpdate：偵測到新版 build 就背景更新，下次開啟生效（另一選項 prompt = 跳「有新版」讓使用者按）
      registerType: 'autoUpdate',
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
      workbox: {
        // 離線時的導覽 fallback：使用者在離線狀態開 /m/ → 回快取的 app 殼
        navigateFallback: '/m/index.html',
        runtimeCaching: [
          {
            // API 走 NetworkFirst：先打網路（5 秒沒回應或離線 → 退回上次快取的結果）
            // → 離線時還看得到「上次載入的美食清單」
            urlPattern: /\/api\/.*/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 50, maxAgeSeconds: 24 * 60 * 60 },
            },
          },
          {
            // 店家照片走 CacheFirst：圖片內容不會變（檔名是 uuid），抓過一次就用快取
            urlPattern: /\/media\/.*/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'media',
              expiration: { maxEntries: 200, maxAgeSeconds: 30 * 24 * 60 * 60 },
            },
          },
        ],
      },
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
