// 12 大類：順序＝篩選 chips 的顯示順序，必須與後端 food/cuisine.py 的 MAJORS 一致。
// 後端才是詞彙表的真相來源；這裡只負責「怎麼顯示」。
export const MAJORS = [
  '日式', '韓式', '中式', '台式', '東南亞', '西式',
  '火鍋', '燒烤', '早午餐', '咖啡甜點', '飲料冰品', '酒吧餐酒館',
]

export const MAJOR_ICON = {
  日式: '🍣', 韓式: '🍲', 中式: '🥢', 台式: '🍜', 東南亞: '🌶️', 西式: '🍔',
  火鍋: '🍲', 燒烤: '🍢', 早午餐: '🍳', 咖啡甜點: '☕', 飲料冰品: '🥤', 酒吧餐酒館: '🍸',
}

// 舊資料（大類還沒回填、或判不出來）的退路：拿原始自由文字猜個圖示，
// 免得整排卡片都是同一個 🍽️。
const LEGACY_ICON = {
  中式: '🥢', 台式: '🥢', 日式: '🍣', 韓式: '🍲', 美式: '🍔',
  義式: '🍝', 泰式: '🌶️', 火鍋: '🍲', 燒烤: '🍢', 早餐: '🍳',
  飲料: '🥤', 咖啡: '☕', 甜點: '🍰', 麵: '🍜',
}

export function iconFor(place) {
  if (place.cuisine_major && MAJOR_ICON[place.cuisine_major]) return MAJOR_ICON[place.cuisine_major]
  const raw = place.cuisine_type || ''
  for (const k in LEGACY_ICON) if (raw.includes(k)) return LEGACY_ICON[k]
  return '🍽️'
}

// 卡片副標用：「大類 · 細類」，兩層都沒有才退回原始文字
export function kindLabel(place) {
  const parts = [place.cuisine_major, place.cuisine_minor].filter(Boolean)
  return parts.join(' · ') || place.cuisine_type || ''
}
