// 卡片清單：純呈現元件。收 places + onSelect，自己不抓資料、不管篩選。
import { iconFor, kindLabel } from './cuisine'

export default function FoodList({ places, onSelect }) {
  if (!places.length) return <div className="list-empty">這個篩選下沒有店家</div>

  return (
    <div className="food-list">
      {places.map((p) => (
        <button key={p.id} className="card" onClick={() => onSelect(p)}>
          {/* emoji 永遠墊底：照片還在載=先看到 emoji；載入失敗=img 自移除、emoji 留下 */}
          <div className="card-thumb">
            <span className="thumb-icon">{iconFor(p)}</span>
            {p.photos && p.photos.length > 0 && (
              <img src={p.photos[0].url} alt="" loading="lazy"
                   onError={(e) => e.currentTarget.remove()} />
            )}
          </div>
          <div className="card-body">
            <div className="card-title">
              <span className="card-name">{p.name}</span>
              <span className={p.visited ? 'tag visited' : 'tag wish'}>{p.status}</span>
            </div>
            <div className="card-sub">
              {p.city && <span>📍 {p.city}{p.district ? ` ${p.district}` : ''}</span>}
              {kindLabel(p) && <span>· {kindLabel(p)}</span>}
              {p.my_rating ? <span>· {'★'.repeat(p.my_rating)}</span> : null}
            </div>
            {p.recommended_items && <div className="card-reco">👍 {p.recommended_items}</div>}
          </div>
        </button>
      ))}
    </div>
  )
}
