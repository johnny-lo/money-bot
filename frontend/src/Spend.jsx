import { useEffect, useMemo, useState } from 'react'
import { getLedger, createRecord, updateRecord, deleteRecord, getReportToken } from './api'
import { applyFilters, chips, hasCond, summarize, toggleCond } from './ledgerFilter.js'
import RecordSheet from './RecordSheet.jsx'

// 消費分頁：月導覽 + 三格頭 + 分類占比 + 流水帳 + 新增/編輯。
// 設計選擇：一個月的明細「一次抓回來」，總額/分類占比都在前端算 ——
// 跟美食頁同一哲學：切畫面不重新連線，手機上才會跟得上手指。
//
// 篩選：點分類長條、點日期標頭 → 條件疊加取交集，點同一個第二次取消。
// 語意與 /report 報表頁共用同一份純函式（ledgerFilter.js），兩邊不會漂移。
export default function Spend() {
  const now = new Date()
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() + 1 })
  const [records, setRecords] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null)   // null=關閉, {}=新增, {...record}=編輯
  const [conds, setConds] = useState({})         // { type?, category?, day?, month? }

  async function load() {
    setLoading(true)
    setError('')
    try {
      const data = await getLedger(ym.y, ym.m)
      setRecords(data.records || [])
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [ym.y, ym.m])

  function shiftMonth(delta) {
    const d = new Date(ym.y, ym.m - 1 + delta, 1)
    // 換月要丟掉日期條件：留著「9/15」跳到 10 月只會篩出空白，
    // 而使用者只會覺得壞了。分類是跨月通用的，留著。
    setConds((c) => toggleCond(toggleCond(c, 'day', ''), 'month', ''))
    setYm({ y: d.getFullYear(), m: d.getMonth() + 1 })
  }

  // 三格頭與分類占比吃**整月**資料，不跟著篩選變 ——
  // 篩選後的數字只出現在摘要列，否則會分不清自己在看整月還是篩選後；
  // 而且分類長條自己就是篩選器，被自己篩到剩一條就沒得點回去了。
  const stats = useMemo(() => {
    let income = 0, expense = 0
    const byCat = {}
    for (const r of records) {
      if (r.type === 'income') income += r.amount
      else {
        expense += r.amount
        const c = r.category || '未分類'
        byCat[c] = (byCat[c] || 0) + r.amount
      }
    }
    const cats = Object.entries(byCat)
      .map(([name, amount]) => ({ name, amount }))
      .sort((a, b) => b.amount - a.amount)
    return { income, expense, net: expense - income, cats }
  }, [records])

  // 給編輯表單的分類候選（這個月用過的分類）
  const knownCats = useMemo(
    () => [...new Set(records.map((r) => r.category).filter((c) => c && c !== '未分類'))],
    [records],
  )

  const filtered = useMemo(() => applyFilters(records, conds), [records, conds])
  const picked = useMemo(() => summarize(filtered), [filtered])

  // 流水帳按日分組（created_at 格式 "YYYY-MM-DD HH:MM"，後端已新到舊排好）
  const byDay = useMemo(() => {
    const groups = []
    let cur = null
    for (const r of filtered) {
      const day = (r.created_at || '').slice(0, 10)
      if (!cur || cur.day !== day) {
        cur = { day, items: [] }
        groups.push(cur)
      }
      cur.items.push(r)
    }
    return groups
  }, [filtered])

  const toggle = (key, value) => setConds((c) => toggleCond(c, key, value))

  async function save(form) {
    if (form.id) {
      await updateRecord(form.type, form.id, {
        item: form.item, amount: form.amount, category: form.category || null,
      })
    } else {
      await createRecord({
        type: form.type, item: form.item, amount: form.amount, category: form.category || null,
      })
    }
    setEditing(null)
    await load()
  }

  async function remove(form) {
    await deleteRecord(form.type, form.id)
    setEditing(null)
    await load()
  }

  // 開完整報表頁（圖表在那邊）。先同步開一個空分頁再填網址 ——
  // 等 await 回來才 window.open 會被當成「非使用者手勢」擋掉。
  async function openReport() {
    const w = window.open('', '_blank')
    try {
      const { token } = await getReportToken()
      const url = `/report?token=${encodeURIComponent(token)}`
      if (w) w.location = url
      else window.location.href = url   // 被擋掉就同頁跳過去
    } catch (e) {
      if (w) w.close()
      setError(String(e.message || e))
    }
  }

  const fmt = (n) => '$' + n.toLocaleString()

  return (
    <div className="spend">
      {/* 月導覽 */}
      <div className="spend-bar">
        <button className="icon-btn" onClick={() => shiftMonth(-1)}>←</button>
        <span className="spend-month">{ym.y} 年 {ym.m} 月</span>
        <button className="icon-btn" onClick={() => shiftMonth(1)}>→</button>
        <button className="report-link" onClick={openReport}>📊 報表</button>
      </div>

      {error && <div className="food-error">{error}</div>}

      {/* 三格頭（整月，不受篩選影響） */}
      <div className="spend-summary">
        <div><div className="lbl">💰 收入</div><div className="val income">{fmt(stats.income)}</div></div>
        <div><div className="lbl">💸 支出</div><div className="val expense">{fmt(stats.expense)}</div></div>
        <div><div className="lbl">📋 淨支出</div><div className="val">{fmt(stats.net)}</div></div>
      </div>

      {/* 分類占比（CSS 長條，不上圖表庫 → bundle 小、離線也畫得出來）。點一條＝篩那個分類 */}
      {stats.cats.length > 0 && (
        <div className="spend-cats">
          {stats.cats.map((c) => (
            <button
              key={c.name}
              className={conds.category === c.name ? 'cat-row active' : 'cat-row'}
              onClick={() => toggle('category', c.name)}
            >
              <span className="cat-name">{c.name}</span>
              <div className="cat-bar">
                <div className="cat-fill" style={{ width: `${(c.amount / stats.expense) * 100}%` }} />
              </div>
              <span className="cat-amt">{fmt(c.amount)}</span>
            </button>
          ))}
        </div>
      )}

      {/* 篩選摘要列：每道條件一顆 chip，可單獨叉掉 */}
      {hasCond(conds) && (
        <div className="filter-bar">
          {chips(conds).map((c) => (
            <button key={c.key} className="filter-chip" onClick={() => toggle(c.key, '')}>
              {c.label} ✕
            </button>
          ))}
          <span className="filter-stats">
            {picked.count} 筆
            {picked.expense > 0 && ` · 支出 ${fmt(picked.expense)}`}
            {picked.income > 0 && ` · 收入 ${fmt(picked.income)}`}
          </span>
          <button className="filter-clear" onClick={() => setConds({})}>清除</button>
        </div>
      )}

      {/* 流水帳（按日分組；點日期標頭＝篩那天，點一筆＝編輯） */}
      {loading ? (
        <div className="list-empty">載入中…</div>
      ) : filtered.length === 0 ? (
        <div className="list-empty">{hasCond(conds) ? '這些條件下沒有紀錄' : '這個月還沒有紀錄'}</div>
      ) : (
        <div className="ledger">
          {byDay.map((g) => (
            <div key={g.day}>
              <button
                className={conds.day === g.day ? 'ledger-day active' : 'ledger-day'}
                onClick={() => toggle('day', g.day)}
              >
                {g.day.slice(5).replace('-', '/')}
              </button>
              {g.items.map((r) => (
                <button key={`${r.type}-${r.id}`} className="ledger-row" onClick={() => setEditing(r)}>
                  <span className="ledger-item">{r.item}</span>
                  {r.category && r.category !== '未分類' && (
                    <span className="ledger-cat">{r.category}</span>
                  )}
                  <span className={r.type === 'income' ? 'ledger-amt income' : 'ledger-amt expense'}>
                    {r.type === 'income' ? '+' : '-'}{fmt(r.amount)}
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* 浮動新增鈕（拇指區右下） */}
      <button className="fab" onClick={() => setEditing({})}>＋</button>

      <RecordSheet
        record={editing}
        knownCats={knownCats}
        onSave={save}
        onDelete={remove}
        onClose={() => setEditing(null)}
      />
    </div>
  )
}
