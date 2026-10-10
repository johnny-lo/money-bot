// 流水帳篩選：純函式，無 React、無 DOM、無 I/O。
//
// **同一份檔給兩個前端吃**：PWA 走 vite build（import 進 Spend.jsx），
// 報表頁走 FastAPI 的 /report/ledger_filter.js 直接載入原始碼。
// 分成兩份複製貼上的下場是兩邊的篩選語意慢慢漂移，使用者在兩個頁面點同一個分類
// 卻看到不同結果 —— 這個 repo 在料理詞彙表上已經記過一次這個教訓。
//
// 跑測試：cd frontend && npm test
//
// 條件模型 conds = { type?, category?, day?, month? }，每一維最多一個值，
// 多維之間取**交集**（疊加）。這正是「這個月飲食花最多的是哪一天」問得出來的原因——
// 取代式篩選只能問單一維度。

// chip 的顯示順序寫死，不跟著使用者點擊的先後跑。
// 順序會動的話，多點一個條件整排 chip 就重排，手指還停在原位就按到別的東西。
const ORDER = ['type', 'category', 'day', 'month']

const TYPE_LABEL = { expense: '支出', income: '收入' }

// 後端 ledger API 的 category 已經把 NULL 正規化成「未分類」，
// 但前端自己組的資料（新增後樂觀更新）可能還是 null，所以這裡再守一次。
const catOf = (r) => r.category || '未分類'

// created_at 是 "YYYY-MM-DD HH:MM"。缺漏時回空字串，讓日期條件自然不命中
// （回 null 會讓 slice 炸掉，回 '今天' 會讓沒時間的紀錄憑空出現在某一天）。
const stampOf = (r) => r.created_at || ''

export function applyFilters(records, conds) {
  const c = conds || {}
  return (records || []).filter((r) => {
    if (c.type && r.type !== c.type) return false
    if (c.category && catOf(r) !== c.category) return false
    if (c.day && stampOf(r).slice(0, 10) !== c.day) return false
    if (c.month && stampOf(r).slice(0, 7) !== c.month) return false
    return true
  })
}

// 點一下加條件，點同一個值第二下取消，點同一維的別的值＝換值。
// 一律回新物件：React 的 setState 認 identity，就地改的話畫面不會重畫。
export function toggleCond(conds, key, value) {
  const next = { ...(conds || {}) }
  if (!value || next[key] === value) delete next[key]
  else next[key] = value
  return next
}

export function hasCond(conds) {
  return Object.keys(conds || {}).length > 0
}

// 摘要列的數字。吃的是**篩選後**的陣列 —— 摘要要跟眼睛看到的那幾筆對得起來。
// 淨支出＝支出－收入，跟三格頭同一個定義。
export function summarize(records) {
  let expense = 0
  let income = 0
  for (const r of records || []) {
    if (r.type === 'income') income += r.amount
    else expense += r.amount
  }
  return { count: (records || []).length, expense, income, net: expense - income }
}

// 給摘要列畫 chip 用。key 拿來叉掉那一維（toggleCond(conds, key, '')）。
export function chips(conds) {
  const c = conds || {}
  return ORDER.filter((k) => c[k]).map((k) => ({ key: k, label: chipLabel(k, c[k]) }))
}

function chipLabel(key, value) {
  if (key === 'type') return TYPE_LABEL[value] || value
  if (key === 'day') return value.slice(5).replace('-', '/')      // 2026-09-15 → 09/15
  if (key === 'month') return value.replace('-', '/')             // 2026-08 → 2026/08
  return value
}
