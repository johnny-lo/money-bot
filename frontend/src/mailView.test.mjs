// 信件分頁純函式的測試（node 內建 test runner：cd frontend && npm test）
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { allEmpty, groupOverview, rowText } from './mailView.js'

const L = [
  { key: 'job', title: '🛡 求職字眼', count: 1 }, { key: 'valued', title: '🛡 重視的公司', count: 0 },
  { key: 'human', title: '🛡 真人來信', count: 2 }, { key: 'login', title: '登入／驗證碼', count: 5 },
]

test('🛡 三層排在前面一組', () => {
  const g = groupOverview(L)
  assert.deepEqual(g.shield.map((x) => x.key), ['job', 'valued', 'human'])
  assert.deepEqual(g.rest.map((x) => x.key), ['login'])
})

test('全部 0 筆＝還沒同步過', () => {
  assert.equal(allEmpty(L), false)
  assert.equal(allEmpty(L.map((x) => ({ ...x, count: 0 }))), true)
})

test('各種列的文字', () => {
  assert.deepEqual(rowText('messages', { date: '2026-10-12', sender: 'a@x', subject: '面試', where: '收件匣', next: null }),
    { main: '面試', sub: '2026-10-12・a@x', badge: '收件匣' })
  assert.equal(rowText('messages', { date: null, sender: 'a@x', subject: 's', where: '資料夾', next: '10/20 丟' }).badge, '10/20 丟')
  assert.equal(rowText('domains', { domain: 'corp.example', since: '2026-05-01', pattern: '面試邀請', count: 2, status: '已確認' }).badge,
    '2 封・已確認')
  assert.equal(rowText('rules', { sender: '@x', pattern: '*', category: '推銷／電子報', status: '已確認', by: 'AI' }).badge,
    '推銷／電子報・已確認')
  assert.equal(rowText('groups', { sender: 'a@x', pattern: 'p', count: 3, last: null }).badge, '3 封')
})

test('重視的公司：待確認的網域看得出來', () => {
  const r = rowText('domains', { domain: 'wait.example', since: '2026-10-14', pattern: '面試 #', count: 3, status: '待確認' })
  assert.equal(r.main, 'wait.example')
  assert.equal(r.badge, '3 封・待確認')
  assert.match(r.sub, /面試 #/)
})
