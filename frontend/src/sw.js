// 自製 service worker（injectManifest 模式）。
// 保留 injectManifest 而非 generateSW：這裡的路由策略（導覽走 precache、API NetworkFirst、
// 圖片 CacheFirst 分開設定）用自己寫的檔案比較清楚，之後要加東西也不受 schema 限制。
import { precacheAndRoute, cleanupOutdatedCaches, createHandlerBoundToURL } from 'workbox-precaching'
import { registerRoute, NavigationRoute } from 'workbox-routing'
import { NetworkFirst, CacheFirst } from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'
import { clientsClaim } from 'workbox-core'

// 新版 SW 立刻接管（配合 registerType: 'autoUpdate'）
self.skipWaiting()
clientsClaim()

// App 殼 precache（build 時 vite-plugin-pwa 會把檔案清單注入 __WB_MANIFEST）
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// 離線時的導覽 fallback：離線開 /m/ → 回快取的 app 殼
registerRoute(new NavigationRoute(createHandlerBoundToURL('/m/index.html')))

// API：先打網路（5 秒沒回應或離線 → 退回上次快取）→ 離線還看得到上次的清單
registerRoute(
  ({ url }) => url.pathname.startsWith('/api/'),
  new NetworkFirst({
    cacheName: 'api',
    networkTimeoutSeconds: 5,
    plugins: [new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 24 * 60 * 60 })],
  }),
)

// 店家照片：CacheFirst（檔名是 uuid 內容不會變）。
registerRoute(
  ({ url }) => url.pathname.startsWith('/media/'),
  new CacheFirst({
    cacheName: 'media-v2',   // v1 曾被 ngrok 攔截頁毒過（回 200+HTML 還被當圖片快取住），
                             // 當時換名整鍋拋棄。已改用 Tailscale Funnel、沒有攔截頁，名字沿用即可。
    plugins: [
      new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 30 * 24 * 60 * 60 }),
    ],
  }),
)
