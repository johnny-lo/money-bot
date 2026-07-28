import { useRef, useState } from 'react'
import { markVisited, uploadPhoto, deletePhoto } from './api'
import { kindLabel } from './cuisine'
import { shrinkImage } from './image'

// 照片來源標示：自己拍的才是回憶，Google 圖只是補位
const SRC_BADGE = { app: '📸', bot: '🤖', google: '🔍' }

// 由下滑上的詳情面板（bottom sheet）。
// 注意：這裡是「宣告式」的 —— 我們只描述「有選中的店就長這樣」，
// 滑入/滑出交給 CSS transform（走 GPU，很順），不自己一幀一幀畫。
export default function PlaceSheet({ place, onClose, onChanged }) {
  const open = !!place
  const [editing, setEditing] = useState(false)   // 「標去過」小表單開關
  const [rating, setRating] = useState(0)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const fileRef = useRef(null)

  // 換選別家店時把表單收起來（用 key 重置也行，這裡手動最直白）
  const placeId = place?.id
  const lastId = useRef(placeId)
  if (placeId !== lastId.current) {
    lastId.current = placeId
    if (editing) setEditing(false)
    if (err) setErr('')
  }

  async function run(action) {
    setBusy(true)
    setErr('')
    try {
      await action()
      await onChanged?.(placeId)   // 重抓資料，面板會拿到新 props
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  function openVisitedForm() {
    setRating(place.my_rating || 0)
    setNote(place.my_note || '')
    setEditing(true)
  }

  const saveVisited = () => run(async () => {
    await markVisited(placeId, rating, note)
    setEditing(false)
  })

  const onPickFile = (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''   // 清掉，讓同一張圖能再選一次
    if (file) run(async () => uploadPhoto(placeId, await shrinkImage(file)))
  }

  const removePhoto = (photo) => {
    if (window.confirm('刪掉這張照片？')) run(() => deletePhoto(photo.id))
  }

  return (
    // 半透明遮罩：點它 → 關閉
    <div className={open ? 'sheet open' : 'sheet'} onClick={onClose}>
      {/* 內層卡片：點它本身不關（擋掉冒泡） */}
      <div className="sheet-card" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        {place && (
          <>
            {place.photos && place.photos.length > 0 && (
              <div className="sheet-photos">
                {place.photos.map((ph) => (
                  <div key={ph.id} className="photo-wrap">
                    <img src={ph.url} alt="" loading="lazy" />
                    <span className="photo-src">{SRC_BADGE[ph.source] || '📷'}</span>
                    <button className="photo-del" onClick={() => removePhoto(ph)} title="刪除">✕</button>
                  </div>
                ))}
              </div>
            )}
            {/* {place.name} 會被 React 自動跳脫 —— 不用像舊版那樣手動 esc() */}
            <h3>{place.name}</h3>
            <div className="sheet-meta">
              {place.status && <span className="badge">{place.status}</span>}
              {kindLabel(place) && <span>🍽️ {kindLabel(place)}</span>}
              {place.city && <span>🗺️ {place.city}{place.district ? ` ${place.district}` : ''}</span>}
              {place.my_rating ? <span>{'★'.repeat(place.my_rating)}</span> : null}
            </div>
            {place.recommended_items && <p>👍 {place.recommended_items}</p>}
            {place.my_note && <p>📝 {place.my_note}</p>}
            {place.caution_summary && <p className="caution">🔥 雷點：{place.caution_summary}</p>}
            {place.address && <p className="addr">📍 {place.address}</p>}

            {err && <p className="sheet-err">⚠️ {err}</p>}

            {editing ? (
              <div className="visited-form">
                {/* 星等：點第 n 顆 = n 分，再點同一顆 = 清除 */}
                <div className="stars">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button key={n} onClick={() => setRating(n === rating ? 0 : n)}>
                      {n <= rating ? '★' : '☆'}
                    </button>
                  ))}
                </div>
                <input
                  className="note-input"
                  placeholder="一句話心得（選填）"
                  value={note}
                  maxLength={120}
                  onChange={(e) => setNote(e.target.value)}
                />
                <div className="sheet-actions">
                  <button className="btn primary" disabled={busy} onClick={saveVisited}>
                    {busy ? '…' : '✅ 儲存'}
                  </button>
                  <button className="btn" disabled={busy} onClick={() => setEditing(false)}>取消</button>
                </div>
              </div>
            ) : (
              <div className="sheet-actions">
                {place.maps_url && (
                  <a className="btn primary" href={place.maps_url} target="_blank" rel="noopener">
                    🧭 導航
                  </a>
                )}
                <button className="btn" disabled={busy} onClick={openVisitedForm}>
                  {place.visited ? '✏️ 改評分' : '✅ 去過了'}
                </button>
                <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
                  {busy ? '…' : '📷 加照片'}
                </button>
                {/* 隱藏的檔案輸入：手機上會跳「拍照 / 相簿」 */}
                <input ref={fileRef} type="file" accept="image/*" hidden onChange={onPickFile} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
