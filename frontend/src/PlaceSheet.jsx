// 由下滑上的詳情面板（bottom sheet）。
// 注意：這裡是「宣告式」的 —— 我們只描述「有選中的店就長這樣」，
// 滑入/滑出交給 CSS transform（走 GPU，很順），不自己一幀一幀畫。
export default function PlaceSheet({ place, onClose }) {
  const open = !!place
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
                {place.photos.map((url, i) => (
                  <img key={i} src={url} alt="" loading="lazy" />
                ))}
              </div>
            )}
            {/* {place.name} 會被 React 自動跳脫 —— 不用像舊版那樣手動 esc() */}
            <h3>{place.name}</h3>
            <div className="sheet-meta">
              {place.status && <span className="badge">{place.status}</span>}
              {place.cuisine_type && <span>🍽️ {place.cuisine_type}</span>}
              {place.my_rating ? <span>{'★'.repeat(place.my_rating)}</span> : null}
            </div>
            {place.recommended_items && <p>👍 {place.recommended_items}</p>}
            {place.my_note && <p>📝 {place.my_note}</p>}
            {place.caution_summary && <p className="caution">🔥 雷點：{place.caution_summary}</p>}
            {place.address && <p className="addr">📍 {place.address}</p>}
            <div className="sheet-actions">
              {place.maps_url && (
                <a className="btn primary" href={place.maps_url} target="_blank" rel="noopener">
                  🧭 導航
                </a>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
