import { RANGES } from './geo'
import { MAJOR_ICON } from './cuisine'

// 純呈現：收「已經算好的分組結果」+ 目前範圍，畫滑桿與磚塊。
// 不自己定位、不自己抓資料、不自己算距離 —— 跟 FoodList/FoodMap 同樣的分工，
// 所有狀態都住在 Food.jsx。
export default function Nearby({
  groups, total, rangeKm, onRangeChange, major, onMajorChange, onRelocate,
}) {
  const idx = Math.max(0, RANGES.findIndex((r) => r.km === rangeKm))
  const range = RANGES[idx]
  const next = RANGES[idx + 1]

  return (
    <div className="nearby">
      <div className="range-row">
        <input
          className="range-slider"
          type="range"
          min="0"
          max={RANGES.length - 1}
          step="1"
          value={idx}
          aria-label="範圍"
          onChange={(e) => onRangeChange(RANGES[Number(e.target.value)].km)}
        />
        <button className="icon-btn" onClick={onRelocate} title="重新定位">📍</button>
      </div>
      <div className="range-caption">
        {range.label} 內 · 約 {range.minutes} 分車程 · 共 {total} 家
      </div>

      {total === 0 ? (
        <div className="list-empty">
          <div>{range.label} 內沒有店家</div>
          {next && (
            <button className="chip" onClick={() => onRangeChange(next.km)}>
              拉大到 {next.label}
            </button>
          )}
        </div>
      ) : (
        <div className="tile-grid">
          {groups.map((g) => (
            <button
              key={g.major}
              className={g.major === major ? 'tile active' : 'tile'}
              onClick={() => onMajorChange(g.major === major ? 'all' : g.major)}
            >
              <span className="tile-icon">{MAJOR_ICON[g.major] || '🍽️'}</span>
              <span className="tile-name">{g.major}</span>
              <span className="tile-count">{g.count} 家</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
