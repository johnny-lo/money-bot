import { useEffect, useRef, useState } from 'react'
import { getRecipes, renameRecipe, deleteRecipe } from './api'

const PLATFORM_ICON = {
  youtube: '▶️', instagram: '📸', tiktok: '🎵',
  facebook: '📘', threads: '🧵',
}

// 食譜分頁：主角是「今天煮什麼」拉霸，清單在下面。
// 隨機抽在前端做 —— 清單整份在手上，抽是瞬間的、離線也能玩。
export default function Recipe() {
  const [recipes, setRecipes] = useState([])
  const [error, setError] = useState('')
  const [rolling, setRolling] = useState(false)
  const [picked, setPicked] = useState(null)     // 抽中的那道
  const [flash, setFlash] = useState('')         // 拉霸滾動中顯示的名字
  const [editing, setEditing] = useState(null)   // 點清單某道 → 操作 sheet
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)

  async function load() {
    try {
      const data = await getRecipes()
      setRecipes(data.recipes || [])
    } catch (e) {
      setError(String(e.message || e))
    }
  }
  useEffect(() => {
    load()
    return () => clearInterval(timer.current)   // 離開分頁時把動畫關掉
  }, [])

  // 拉霸：快速輪播名字、逐步放慢、最後停在 random 抽中的那道。
  // 結果「先抽好」，動畫只是儀式感 —— 跟真的拉霸一樣。
  function roll() {
    if (!recipes.length || rolling) return
    const winner = recipes[Math.floor(Math.random() * recipes.length)]
    setRolling(true)
    setPicked(null)
    let delay = 50          // 起跑很快
    const spin = () => {
      setFlash(recipes[Math.floor(Math.random() * recipes.length)].name)
      delay *= 1.18          // 每跳一次慢 18% → 自然減速
      if (delay < 450) {
        timer.current = setTimeout(spin, delay)
      } else {
        setFlash('')
        setPicked(winner)
        setRolling(false)
      }
    }
    spin()
  }

  function openSheet(r) {
    setEditing(r)
    setNewName(r.name)
  }

  async function run(action) {
    setBusy(true)
    try {
      await action()
      await load()
      setEditing(null)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const saveRename = () => {
    if (!newName.trim()) return
    run(() => renameRecipe(editing.id, newName.trim()))
  }

  const removeRecipe = () => {
    if (window.confirm(`刪掉「${editing.name}」？`)) {
      run(async () => {
        await deleteRecipe(editing.id)
        if (picked?.id === editing.id) setPicked(null)
      })
    }
  }

  const icon = (r) => PLATFORM_ICON[r.platform] || '🔗'

  return (
    <div className="recipe">
      {error && <div className="food-error">{error}</div>}

      {/* 拉霸區 */}
      <div className="slot">
        <div className={rolling ? 'slot-window rolling' : 'slot-window'}>
          {rolling ? (flash || '…')
            : picked ? picked.name
            : recipes.length ? '今天煮什麼？' : '先去 #🍳-食譜 丟幾個連結'}
        </div>
        {picked && !rolling && (
          <div className="slot-result">
            <a className="btn primary" href={picked.url} target="_blank" rel="noopener">
              {icon(picked)} 點開照做
            </a>
            <button className="btn" onClick={roll}>🎰 再抽一次</button>
          </div>
        )}
        {!picked && (
          <button className="btn primary slot-btn" disabled={!recipes.length || rolling} onClick={roll}>
            🎰 拉一下
          </button>
        )}
      </div>

      {/* 清單 */}
      <div className="recipe-list">
        <div className="recipe-count">已收錄 {recipes.length} 道</div>
        {recipes.map((r) => (
          <button key={r.id} className="ledger-row" onClick={() => openSheet(r)}>
            <span className="recipe-icon">{icon(r)}</span>
            <span className="ledger-item">{r.name}</span>
          </button>
        ))}
      </div>

      {/* 操作 sheet：開連結 / 改名 / 刪除 */}
      <div className={editing ? 'sheet open' : 'sheet'} onClick={() => setEditing(null)}>
        <div className="sheet-card" onClick={(e) => e.stopPropagation()}>
          <div className="sheet-handle" />
          {editing && (
            <>
              <h3>{icon(editing)} {editing.name}</h3>
              <input className="note-input" value={newName} maxLength={60}
                     onChange={(e) => setNewName(e.target.value)} />
              <div className="sheet-actions">
                <a className="btn primary" href={editing.url} target="_blank" rel="noopener">開連結</a>
                <button className="btn" disabled={busy || newName.trim() === editing.name}
                        onClick={saveRename}>✏️ 改名</button>
                <button className="btn danger" disabled={busy} onClick={removeRecipe}>🗑️ 刪除</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
