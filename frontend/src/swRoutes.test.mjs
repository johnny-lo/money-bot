// service worker 路由判斷的測試（node 內建 test runner：cd frontend && npm test）
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { isCachedApi } from './swRoutes.js'

test('美食／影片等分頁的 API 照舊進離線快取', () => {
  assert.equal(isCachedApi('/api/food/places'), true)
  assert.equal(isCachedApi('/api/videos'), true)
  assert.equal(isCachedApi('/api/report/ledger'), true)
})

test('信件 API 不進快取：每個搜尋字／頁／層都是不同網址，會把其他分頁的 50 格擠光', () => {
  assert.equal(isCachedApi('/api/mail/overview'), false)
  assert.equal(isCachedApi('/api/mail/layers/job'), false)
})

test('非 /api/ 路徑本來就不歸這條路由', () => {
  assert.equal(isCachedApi('/media/abc.jpg'), false)
  assert.equal(isCachedApi('/m/index.html'), false)
})

test('前綴要比對完整路段：/api/mailbox 之類不是信件 API，照舊快取', () => {
  assert.equal(isCachedApi('/api/mailbox'), true)
})
