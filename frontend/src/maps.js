// 載入 Google Maps JS SDK —— 整個 app 只載一次（用模組層級的 _promise 鎖住）。
// 回傳我們要用的幾個 class（Map / AdvancedMarkerElement / PinElement）。
let _promise = null

export function loadMaps() {
  if (_promise) return _promise   // 已經在載 / 載過 → 直接回同一個 promise
  _promise = new Promise((resolve, reject) => {
    const key = import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY
    if (!key) {
      reject(new Error('缺少 Google Maps 金鑰（frontend/.env 的 VITE_GOOGLE_MAPS_BROWSER_KEY）'))
      return
    }
    // Maps 載好後會呼叫這個 callback（名字寫進下面的 script src）
    window.__initGmaps = async () => {
      // importLibrary 只把需要的部分載進來（官方推薦做法）
      const { Map } = await google.maps.importLibrary('maps')
      const { AdvancedMarkerElement, PinElement } = await google.maps.importLibrary('marker')
      resolve({ Map, AdvancedMarkerElement, PinElement })
    }
    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${key}&v=weekly&loading=async&callback=__initGmaps`
    script.async = true
    script.onerror = () => reject(new Error('Google Maps 載入失敗'))
    document.head.appendChild(script)
  })
  return _promise
}
