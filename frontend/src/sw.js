// 自製 service worker（injectManifest 模式）。
// 為什麼不用 generateSW：它的設定 schema 不允許幫 fetch 加自訂 header，
// 而我們需要在抓 /media 圖片時帶 ngrok-skip-browser-warning ——
// <img> 標籤帶不了 header，但 SW 攔截後重發的請求可以。
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
// requestWillFetch 把請求換成帶 ngrok 跳過攔截頁 header 的版本 ——
// 沒有這個，ngrok 免費版會對圖片回 200+HTML 攔截頁，還會被當成圖片快取住（v1 的事故）。
const ngrokBypassPlugin = {
  requestWillFetch: async ({ request }) =>
    new Request(request.url, { headers: { 'ngrok-skip-browser-warning': 'true' } }),
}

registerRoute(
  ({ url }) => url.pathname.startsWith('/media/'),
  new CacheFirst({
    cacheName: 'media-v2',   // v1 被攔截頁毒過，換名拋棄整鍋
    plugins: [
      ngrokBypassPlugin,
      new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 30 * 24 * 60 * 60 }),
    ],
  }),
)
