import { useEffect, useMemo, useState } from 'react'
import { getVideos, updateVideo, addVideoTag, removeVideoTag, deleteVideo } from './api'

// 🎥 歷史教學影片：按主題書架瀏覽 + 標籤/關鍵字搜尋。點卡片 → sheet 編輯主題/標籤。
export default function Videos() {
  const [videos, setVideos] = useState([])
  const [error, setError] = useState('')
  const [topic, setTopic] = useState('全部')   // 選中的書架
  const [q, setQ] = useState('')               // 搜尋字
  const [editing, setEditing] = useState(null) // 點某支 → 編輯 sheet
  const [newTag, setNewTag] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  async function load() {
    try { setVideos((await getVideos()).videos || []) }
    catch (e) { setError(String(e.message || e)) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  // 書架 = 出現過的 topic，**依影片數由多到少排**並帶上數量。
  // 為什麼要排：33 支影片散在 21 個書架，大半只有 1 支。照資料庫回傳順序的話，
  // 真正有東西的書架會被埋在一堆只有一支的書架後面，得橫捲很久才找得到。
  // 帶數量則是讓「這個書架值不值得點」一眼看得出來，不用逐個點進去試。
  const topics = useMemo(() => {
    const n = new Map()
    for (const v of videos) if (v.topic) n.set(v.topic, (n.get(v.topic) || 0) + 1)
    const sorted = [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    return [['全部', videos.length], ...sorted]
  }, [videos])
  const allTags = useMemo(
    () => [...new Set(videos.flatMap((v) => v.tags || []))], [videos])

  // 過濾：先套書架，再套搜尋（比對標題 + 標籤）
  const shown = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return videos.filter((v) => {
      if (topic !== '全部' && v.topic !== topic) return false
      if (!kw) return true
      const hay = (v.title + ' ' + (v.tags || []).join(' ')).toLowerCase()
      return hay.includes(kw)
    })
  }, [videos, topic, q])

  async function run(action) {
    setBusy(true)
    try { await action(); await load() }
    catch (e) { setError(String(e.message || e)) }
    finally { setBusy(false) }
  }

  // sheet 內操作後，重新從最新 videos 取這支以刷新 chips
  const fresh = editing ? videos.find((v) => v.id === editing.id) || editing : null

  return (
    <div className="video">
      {error && <div className="food-error">{error}</div>}

      {/* 書架 chips + 搜尋 */}
      <div className="video-bar">
        <div className="chips">
          {topics.map(([t, n]) => (
            <button key={t} className={t === topic ? 'chip active' : 'chip'}
                    onClick={() => setTopic(t)}>
              {t}<span className="chip-n">{n}</span>
            </button>
          ))}
        </div>
        <input className="video-search" placeholder="🔍 搜尋標題或標籤"
               value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {/* 清單 */}
      <div className="video-list">
        <div className="recipe-count">{shown.length} 支影片</div>
        {loading && <div className="video-empty">載入中…</div>}
        {!loading && shown.length === 0 && (
          <div className="video-empty">
            {videos.length === 0
              ? '還沒有影片。把 YouTube 連結丟進 Discord 的 #📜-歷史教學 頻道就會自動收錄。'
              : '這個條件下沒有影片，換個書架或清掉搜尋字看看。'}
          </div>
        )}
        {shown.map((v) => (
          <button key={v.id} className="video-card" onClick={() => { setEditing(v); setNewTag('') }}>
            <div className="video-thumb">
              {v.thumbnail
                ? <img src={v.thumbnail} alt="" loading="lazy" />
                : '🎥'}
            </div>
            <div className="video-info">
              <div className="video-title">{v.title}</div>
              <div className="video-sub">
                {v.topic && <span className="tag visited">{v.topic}</span>}
                {v.channel && <span> {v.channel}</span>}
              </div>
              {(v.tags || []).length > 0 && (
                <div className="video-tags">{v.tags.map((t) => <span key={t} className="mini-tag">{t}</span>)}</div>
              )}
            </div>
          </button>
        ))}
      </div>

      {/* 編輯 sheet */}
      <div className={editing ? 'sheet open' : 'sheet'} onClick={() => setEditing(null)}>
        <div className="sheet-card" onClick={(e) => e.stopPropagation()}>
          <div className="sheet-handle" />
          {fresh && (
            <>
              <h3>🎥 {fresh.title}</h3>

              {/* 主題（自由字串，建議清單來自既有 topics） */}
              <label className="video-field">主題
                <input className="note-input" defaultValue={fresh.topic || ''} list="topic-list"
                       onBlur={(e) => {
                         const t = e.target.value.trim()
                         if (t !== (fresh.topic || '')) run(() => updateVideo(fresh.id, { topic: t }))
                       }} />
              </label>
              <datalist id="topic-list">
                {topics.filter(([t]) => t !== '全部').map(([t]) => <option key={t} value={t} />)}
              </datalist>

              {/* 標籤 chips：點 ✕ 刪 */}
              <div className="sheet-tags">
                {(fresh.tags || []).map((t) => (
                  <span key={t} className="mini-tag removable" onClick={() =>
                    !busy && run(() => removeVideoTag(fresh.id, t))}>{t} ✕</span>
                ))}
              </div>

              {/* 加標籤（建議清單來自所有既有標籤） */}
              <div className="tag-add">
                <input className="note-input" placeholder="加標籤" list="tag-list"
                       value={newTag} onChange={(e) => setNewTag(e.target.value)} />
                <datalist id="tag-list">
                  {allTags.map((t) => <option key={t} value={t} />)}
                </datalist>
                <button className="btn" disabled={busy || !newTag.trim()} onClick={() =>
                  run(async () => { await addVideoTag(fresh.id, newTag.trim()); setNewTag('') })}>＋</button>
              </div>

              <div className="sheet-actions">
                <a className="btn primary" href={fresh.url} target="_blank" rel="noopener">▶️ 開啟</a>
                <button className="btn danger" disabled={busy} onClick={() => {
                  if (window.confirm(`刪掉「${fresh.title}」？`))
                    run(async () => { await deleteVideo(fresh.id); setEditing(null) })
                }}>🗑️ 刪除</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
