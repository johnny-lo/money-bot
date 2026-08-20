// 「手機卡在舊版」的解法。純函式無 React，可用
//   node --input-type=module -e "..."  直接驗（沿用 geo.js 的姿態，不為此引入測試框架）。
//
// 為什麼需要這個檔：sw.js 用 NavigationRoute 把所有導覽都導到 precache 的殼，
// 所以殼永遠不走網路，只有 SW 自己更新後才會換。而瀏覽器只在「導覽發生」時才去
// 檢查 sw.js —— 桌機按重新整理就算一次，但手機主畫面 App 沒有重整鈕，iOS 又是
// 暫停而非終止，從 App 切換器切回來常常不算導覽 → 檢查永遠不觸發，就一直卡舊版。

/** 目前這份 app 是由哪個 bundle 檔載入的（檔名帶內容雜湊，內容一變檔名就變）。 */
export function currentBundle() {
  const el = document.querySelector('script[type="module"][src*="/assets/index-"]')
  return el ? bundleName(el.getAttribute('src')) : ''
}

/** 從一段 HTML 裡取出 bundle 檔名。純函式。 */
export function bundleName(html) {
  const m = String(html || '').match(/assets\/index-[A-Za-z0-9_-]+\.js/)
  return m ? m[0] : ''
}

/**
 * 手上這份是不是落後了。兩邊都要有值才敢判定——抓不到就當作沒事，
 * 寧可漏報也不要在離線/暫時抓不到時亂跳「有新版」。
 */
export function isStale(current, server) {
  return Boolean(current && server && current !== server)
}

/**
 * 直接問伺服器現在的殼指向哪個 bundle。
 *
 * cache:'no-store' + 這個請求不是 navigate（不會被 NavigationRoute 攔），所以真的會出網路。
 *
 * **必須帶 ngrok-skip-browser-warning**：不帶的話 ngrok 免費版會回攔截頁的 HTML，
 * 解不出 bundle 檔名 → 永遠判定「沒有新版」→ 這個偵測就等於沒做。
 * （這正是「瀏覽器抓 sw.js 沒辦法帶 header、於是拿到攔截頁、於是 SW 永遠更新不了」
 *   那個根因的同一顆地雷；我們自己發的 fetch 至少躲得掉。）
 */
export async function fetchServerBundle() {
  const res = await fetch('/m/index.html', {
    cache: 'no-store',
    headers: { 'ngrok-skip-browser-warning': 'true' },
  })
  return bundleName(await res.text())
}


/**
 * 強制換新殼。**不能只做 location.reload()** —— sw.js 的 NavigationRoute 會把
 * precache 裡的舊殼再餵回來一次，重整幾次都一樣。
 *
 * 順序：先給 SW 正常更新的機會（skipWaiting 會讓它接管 → controllerchange 自動重整）；
 * 真的沒動靜才走最後手段：清快取 + 反註冊 + 重載。
 *
 * 清快取時**刻意保留 media**：那是店家照片（30 天快取），砍掉等於叫使用者用行動網路
 * 重抓幾十張圖，而它跟「殼是不是舊的」無關。
 */
export async function forceUpdate() {
  try {
    const reg = await navigator.serviceWorker.getRegistration()
    if (reg) {
      await reg.update()
      if (reg.waiting || reg.installing) return   // 交給 controllerchange 接手
    }
  } catch { /* 落到下面的最後手段 */ }
  try {
    const keys = await caches.keys()
    await Promise.all(
      keys.filter((k) => !k.startsWith('media')).map((k) => caches.delete(k)),
    )
    const reg = await navigator.serviceWorker.getRegistration()
    if (reg) await reg.unregister()
  } catch { /* 清不掉也還是重載，至少試一次 */ }
  window.location.reload()
}
