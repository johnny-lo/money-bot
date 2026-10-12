import { useEffect, useRef, useState } from 'react'
import { getMailOverview, getMailLayer } from './api'
import { allEmpty, groupOverview, rowText } from './mailView'

const PAGE = 200   // 一次抓幾筆；跟後端 limit 預設值一致

// 📬 信件整理名單：唯讀。總覽是一格一層的小卡（名稱＋筆數），點進去看那一層的名單。
// 這頁只「看」，不改任何東西——規則怎麼確認／退回仍在 Discord 做。
export default function Mail() {
  // layerKey = null 代表在總覽；有值代表在那一層的列表頁。
  // 不裝路由套件：整個 app 只有這一層深，一個 state 就夠，少一個依賴少一個要學的東西。
  const [open, setOpen] = useState(null)   // {key, title} | null

  return open
    ? <MailLayer layer={open} onBack={() => setOpen(null)} />
    : <MailOverview onOpen={setOpen} />
}

function MailOverview({ onOpen }) {
  const [layers, setLayers] = useState(null)   // null＝還沒抓回來，跟「抓回來是空陣列」要分開
  const [error, setError] = useState('')

  // 空依賴陣列 [] ＝只在元件第一次出現時跑一次。
  // 從列表頁返回時 MailOverview 會重新掛載、重抓一次，數字不會停在舊的。
  useEffect(() => {
    getMailOverview()
      .then((d) => setLayers(d.layers || []))
      .catch((e) => setError(String(e.message || e)))
  }, [])

  if (error) return <div className="mail"><div className="food-error">{error}</div></div>
  if (!layers) return <div className="mail"><div className="mail-empty">載入中…</div></div>

  // 全 0 筆要明講「還沒同步過」：畫一排 0 看起來像「整理過了、什麼都沒抓到」，會誤導。
  if (allEmpty(layers)) {
    return <div className="mail"><div className="mail-empty">還沒同步過信件</div></div>
  }

  const { shield, rest } = groupOverview(layers)
  const grid = (items) => (
    <div className="mail-grid">
      {items.map((l) => (
        <button key={l.key} className="mail-tile" onClick={() => onOpen({ key: l.key, title: l.title })}>
          <span className="mail-tile-title">{l.title}</span>
          <span className="mail-tile-n">{l.count}</span>
        </button>
      ))}
    </div>
  )

  return (
    <div className="mail">
      <div className="mail-scroll">
        <div className="recipe-count">🛡 保護名單（不會被整理掉）</div>
        {grid(shield)}
        <div className="recipe-count">其他類別</div>
        {grid(rest)}
      </div>
    </div>
  )
}

function MailLayer({ layer, onBack }) {
  const [q, setQ] = useState('')               // 輸入框裡「現在打的字」
  const [debouncedQ, setDebouncedQ] = useState('')   // 停手 300ms 後才採用的字，真正拿去打 API
  const [data, setData] = useState(null)       // {kind, total}
  const [rows, setRows] = useState([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 每次重抓遞增；回應回來時比對，不是最新一次的就丟掉。
  // 為什麼要：搜尋時網路回應不保證照發出的順序回來，慢的舊回應若後到，
  // 畫面會被舊搜尋字的結果蓋掉，而搜尋框裡寫的卻是新的字。
  const seq = useRef(0)

  // debounce：q 每變一次就排一個 300ms 的計時器；300ms 內又變了，cleanup 會先把舊計時器清掉。
  // 結果＝使用者停止輸入 300ms 後才採用，打「面試邀請」四個字只會打一次 API 而不是四次。
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])

  // 換層或搜尋字定案 → 從頭（offset 0）重抓並「取代」現有列
  useEffect(() => {
    const mine = ++seq.current
    setLoading(true)
    setError('')
    getMailLayer(layer.key, { q: debouncedQ, offset: 0, limit: PAGE })
      .then((d) => {
        if (mine !== seq.current) return
        setData({ kind: d.kind, total: d.total })
        setRows(d.rows || [])
        setOffset(0)
      })
      .catch((e) => { if (mine === seq.current) setError(String(e.message || e)) })
      .finally(() => { if (mine === seq.current) setLoading(false) })
  }, [layer.key, debouncedQ])

  // 載入更多：offset 加一頁，抓下一段「接在後面」。
  async function loadMore() {
    const mine = ++seq.current
    const next = offset + PAGE
    setLoading(true)
    try {
      const d = await getMailLayer(layer.key, { q: debouncedQ, offset: next, limit: PAGE })
      if (mine !== seq.current) return
      setRows((prev) => [...prev, ...(d.rows || [])])
      setData({ kind: d.kind, total: d.total })
      setOffset(next)
    } catch (e) {
      if (mine === seq.current) setError(String(e.message || e))
    } finally {
      if (mine === seq.current) setLoading(false)
    }
  }

  const kind = data?.kind
  const total = data?.total ?? 0

  return (
    <div className="mail">
      <div className="mail-bar">
        <div className="mail-head">
          <button className="btn" onClick={onBack}>← 返回</button>
          <div className="mail-title">{layer.title}</div>
        </div>
        <input className="mail-search" placeholder="🔍 搜尋寄件者或主旨"
               value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div className="mail-list">
        {error && <div className="food-error">{error}</div>}
        {data && <div className="recipe-count">{total} 筆</div>}
        {loading && rows.length === 0 && <div className="mail-empty">載入中…</div>}
        {!loading && !error && rows.length === 0 && (
          <div className="mail-empty">{debouncedQ ? '沒有符合的結果' : '這一層目前沒有信件'}</div>
        )}

        {rows.map((r, i) => {
          const t = rowText(kind, r)
          // 列沒有穩定 id，用位置當 key：這份名單只會整批取代或往後接，不會在中間插入／重排，用 index 不會錯位
          return (
            <div key={i} className="mail-row">
              <div className="mail-row-info">
                <div className="mail-row-main">{t.main}</div>
                <div className="mail-row-sub">{t.sub}</div>
              </div>
              {t.badge && <span className="mini-tag">{t.badge}</span>}
            </div>
          )
        })}

        {rows.length < total && (
          <button className="btn mail-more" disabled={loading} onClick={loadMore}>
            {loading ? '載入中…' : '載入更多'}
          </button>
        )}
      </div>
    </div>
  )
}
