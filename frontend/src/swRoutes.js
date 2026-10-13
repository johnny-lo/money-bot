// service worker 的路由判斷：無 workbox、無 DOM，所以能直接用 node 內建 runner 測。
//
// 為什麼抽出來：「哪些網址進離線快取」是規則，sw.js 一 import workbox 就只能在瀏覽器裡跑。

// 這些前綴的 API 不進離線快取。
// 信件：名單的每個搜尋字／頁／層都是不同網址，'api' 快取只有 50 格（LRU），
// 翻幾頁、搜幾個字就會把美食／影片等分頁的離線快取擠光。信件寄件者與主旨也是私人資料，
// 沒必要在手機的快取裡多留一份。代價：離線時信件分頁只會顯示連線錯誤，不影響其他分頁。
// 尾端的 / 不能省，否則 /api/mailbox 之類不相干的路徑也被排除。
const UNCACHED_API_PREFIXES = ['/api/mail/']

// 哪些 /api/ 路徑要進 'api' 離線快取。
export function isCachedApi(pathname) {
  return pathname.startsWith('/api/')
    && !UNCACHED_API_PREFIXES.some((p) => pathname.startsWith(p))
}
