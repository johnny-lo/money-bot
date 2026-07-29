// 距離/分組純函式 + 範圍常數。無 I/O、無 React —— 可以用 node 直接跑：
//   node --input-type=module -e "import {haversineKm} from './frontend/src/geo.js'; ..."
//
// 車程分鐘是**手工校準的常數表，不是公式**：短程走市區、長程走國道，
// 均速差兩倍以上，線性公式套不住。km×3 會把 30km 算成 90 分（實際約 40 分），
// 使用者看到就永遠不會按那一檔，等於白做。只有五檔，查表比公式誠實也準確。
export const RANGES = [
  { km: 1, label: '1 km', minutes: 5 },    // 含紅綠燈與停車
  { km: 3, label: '3 km', minutes: 10 },   // 中壢區內
  { km: 5, label: '5 km', minutes: 15 },
  { km: 10, label: '10 km', minutes: 20 }, // 中壢→桃園市區
  { km: 30, label: '30 km', minutes: 40 }, // 中壢→竹北約 30 分、→台北約 50 分
]

export const DEFAULT_RANGE_KM = 5

// 沒有大類的店歸這裡，才不會在「附近有什麼」裡憑空消失
export const OTHER = '其他'

const EARTH_R_KM = 6371

export function haversineKm(a, b) {
  // 缺座標回 Infinity 而不是 0 —— 回 0 會讓它出現在每一個範圍裡
  if (!a || !b || a.lat == null || a.lng == null || b.lat == null || b.lng == null) {
    return Infinity
  }
  const toRad = (deg) => (deg * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_R_KM * Math.asin(Math.sqrt(h))
}

// 依大類分組計數。家數多的排前面（決策資訊：1 家的日式跟 6 家的日式不一樣），
// 同數量時用名稱排以求穩定；「其他」永遠墊底。
export function groupByMajor(places) {
  const counts = new Map()
  for (const p of places) {
    const key = p.cuisine_major || OTHER
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([major, count]) => ({ major, count }))
    .sort((x, y) => {
      if (x.major === OTHER) return 1
      if (y.major === OTHER) return -1
      return y.count - x.count || x.major.localeCompare(y.major)
    })
}
