// 流水帳篩選純函式的測試。無框架、無 DOM —— Node 內建 test runner 直接跑：
//   cd frontend && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { applyFilters, chips, hasCond, summarize, toggleCond } from './ledgerFilter.js'

const R = [
  { id: 1, type: 'expense', item: '午餐', amount: 150, category: '飲食', created_at: '2026-09-15 12:30' },
  { id: 2, type: 'expense', item: '晚餐', amount: 250, category: '飲食', created_at: '2026-09-16 19:00' },
  { id: 3, type: 'expense', item: '捷運', amount: 60, category: '交通', created_at: '2026-09-15 08:10' },
  { id: 4, type: 'income', item: '薪水', amount: 50000, category: '薪資', created_at: '2026-09-05 10:00' },
  { id: 5, type: 'expense', item: '不明', amount: 99, category: '未分類', created_at: '2026-08-15 09:00' },
]

test('空條件＝原樣回傳（同一份陣列內容，不多不少）', () => {
  assert.deepEqual(applyFilters(R, {}).map((r) => r.id), [1, 2, 3, 4, 5])
  assert.equal(hasCond({}), false)
})

test('單一條件：分類', () => {
  assert.deepEqual(applyFilters(R, { category: '飲食' }).map((r) => r.id), [1, 2])
})

test('單一條件：日期取到日，不受時分影響', () => {
  assert.deepEqual(applyFilters(R, { day: '2026-09-15' }).map((r) => r.id), [1, 3])
})

test('單一條件：月份（全部月份模式點長條圖用）', () => {
  assert.deepEqual(applyFilters(R, { month: '2026-08' }).map((r) => r.id), [5])
})

test('單一條件：收支類型', () => {
  assert.deepEqual(applyFilters(R, { type: 'income' }).map((r) => r.id), [4])
})

test('疊加是交集，不是取代——這正是「這個月飲食花最多的是哪一天」問得出來的原因', () => {
  assert.deepEqual(applyFilters(R, { category: '飲食', day: '2026-09-15' }).map((r) => r.id), [1])
  assert.deepEqual(applyFilters(R, { category: '飲食', type: 'income' }), [])
})

test('category 為空/null 的紀錄用「未分類」比對（後端已正規化，前端也要守著）', () => {
  const rows = [{ id: 9, type: 'expense', amount: 10, category: null, created_at: '2026-09-01 00:00' }]
  assert.deepEqual(applyFilters(rows, { category: '未分類' }).map((r) => r.id), [9])
})

test('created_at 缺漏不會炸，也不會被日期條件誤命中', () => {
  const rows = [{ id: 9, type: 'expense', amount: 10, category: '飲食' }]
  assert.deepEqual(applyFilters(rows, { day: '2026-09-15' }), [])
  assert.deepEqual(applyFilters(rows, {}).map((r) => r.id), [9])
})

test('toggleCond：點第一次加條件，點同一個第二次取消', () => {
  const one = toggleCond({}, 'category', '飲食')
  assert.deepEqual(one, { category: '飲食' })
  assert.deepEqual(toggleCond(one, 'category', '飲食'), {})
})

test('toggleCond：點同一維度的不同值＝換值，不是疊兩個', () => {
  assert.deepEqual(toggleCond({ category: '飲食' }, 'category', '交通'), { category: '交通' })
})

test('toggleCond 不改原物件（React setState 要新物件才會重畫）', () => {
  const before = { category: '飲食' }
  toggleCond(before, 'day', '2026-09-15')
  assert.deepEqual(before, { category: '飲食' })
})

test('toggleCond：空值＝清掉那一維（select 選「全部分類」走這條）', () => {
  assert.deepEqual(toggleCond({ category: '飲食', day: '2026-09-15' }, 'category', ''), { day: '2026-09-15' })
})

test('summarize：支出/收入分開加總，淨支出＝支出－收入', () => {
  assert.deepEqual(summarize(R), { count: 5, expense: 559, income: 50000, net: -49441 })
  assert.deepEqual(summarize([]), { count: 0, expense: 0, income: 0, net: 0 })
})

test('summarize 吃的是篩選後的結果（摘要列的數字＝眼睛看到的那幾筆）', () => {
  assert.deepEqual(summarize(applyFilters(R, { category: '飲食' })),
                   { count: 2, expense: 400, income: 0, net: 400 })
})

test('chips：每道條件一顆，可單獨叉掉；日期縮成 MM/DD', () => {
  assert.deepEqual(chips({ category: '飲食', day: '2026-09-15', type: 'expense', month: '2026-08' }), [
    { key: 'type', label: '支出' },
    { key: 'category', label: '飲食' },
    { key: 'day', label: '09/15' },
    { key: 'month', label: '2026/08' },
  ])
  assert.deepEqual(chips({}), [])
})

test('chips 順序固定（條件的加入順序不該讓 chip 跳來跳去）', () => {
  const a = chips({ day: '2026-09-15', category: '飲食' })
  const b = chips({ category: '飲食', day: '2026-09-15' })
  assert.deepEqual(a, b)
})
