// 信件列表頁狀態轉換的測試（node 內建 test runner：cd frontend && npm test）
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { initialLayerState, layerReducer } from './mailLayerState.js'

const page1 = { kind: 'messages', total: 450, rows: Array.from({ length: 200 }, (_, i) => ({ subject: `s${i}` })) }
const page2 = { kind: 'messages', total: 450, rows: Array.from({ length: 200 }, (_, i) => ({ subject: `t${i}` })) }

// 一路走到「舊搜尋字已載入第一頁」的狀態
const loadedOld = layerReducer(initialLayerState, { type: 'loaded', d: page1 })

test('新搜尋失敗：不能留著舊搜尋的列、總數與 offset（否則「載入更多」會用新字接舊結果）', () => {
  let s = layerReducer(loadedOld, { type: 'reload' })
  s = layerReducer(s, { type: 'failed', error: '連線失敗' })
  assert.deepEqual(s.rows, [])
  assert.equal(s.data, null)
  assert.equal(s.offset, 0)
  assert.equal(s.error, '連線失敗')
  assert.equal(s.loading, false)
})

test('新搜尋一開始就清空，舊列不會在載入中殘留', () => {
  const s = layerReducer(loadedOld, { type: 'reload' })
  assert.deepEqual(s.rows, [])
  assert.equal(s.data, null)
  assert.equal(s.loading, true)
  assert.equal(s.error, '')
})

test('載入更多一開始就清掉上一次的錯誤，成功後錯誤條不會殘留', () => {
  let s = layerReducer(loadedOld, { type: 'more' })
  s = layerReducer(s, { type: 'failed', error: '逾時' })
  assert.equal(s.error, '逾時')
  s = layerReducer(s, { type: 'more' })
  assert.equal(s.error, '')
  s = layerReducer(s, { type: 'moreLoaded', d: page2, offset: 200 })
  assert.equal(s.error, '')
})

test('載入更多失敗：已顯示的列與 offset 原封不動，可以直接重試同一段', () => {
  let s = layerReducer(loadedOld, { type: 'more' })
  s = layerReducer(s, { type: 'failed', error: '逾時' })
  assert.equal(s.rows.length, 200)
  assert.equal(s.offset, 0)
  assert.equal(s.loading, false)
})

test('載入更多成功：接在後面、offset 前進', () => {
  let s = layerReducer(loadedOld, { type: 'more' })
  s = layerReducer(s, { type: 'moreLoaded', d: page2, offset: 200 })
  assert.equal(s.rows.length, 400)
  assert.equal(s.rows[0].subject, 's0')
  assert.equal(s.rows[200].subject, 't0')
  assert.equal(s.offset, 200)
  assert.equal(s.data.total, 450)
})

test('首頁載入成功：取代現有列、offset 歸零', () => {
  const s = layerReducer(loadedOld, { type: 'loaded', d: { kind: 'messages', total: 1, rows: [{ subject: 'x' }] } })
  assert.deepEqual(s.rows, [{ subject: 'x' }])
  assert.equal(s.offset, 0)
  assert.equal(s.data.total, 1)
})
