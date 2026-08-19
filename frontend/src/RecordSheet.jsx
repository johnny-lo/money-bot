import { useEffect, useState } from 'react'

// 新增 / 編輯一筆收支的 bottom sheet。
// record = null（關閉）/ {}（新增）/ {...筆資料}（編輯）。
export default function RecordSheet({ record, knownCats, onSave, onDelete, onClose }) {
  const open = record !== null
  const isEdit = !!record?.id
  const [type, setType] = useState('expense')
  const [item, setItem] = useState('')
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // 每次打開（record 換了）就帶入該筆內容；新增則清空
  useEffect(() => {
    if (record === null) return
    setType(record.type || 'expense')
    setItem(record.item || '')
    setAmount(record.amount != null ? String(record.amount) : '')
    setCategory(record.category && record.category !== '未分類' ? record.category : '')
    setErr('')
  }, [record])

  async function run(action) {
    setBusy(true)
    setErr('')
    try {
      await action()
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  function submit() {
    const amt = parseInt(amount, 10)
    if (!item.trim()) { setErr('請輸入項目名稱'); return }
    if (!amt || amt <= 0) { setErr('請輸入有效金額'); return }
    run(() => onSave({ id: record?.id, type, item: item.trim(), amount: amt, category: category.trim() }))
  }

  function removeRecord() {
    if (window.confirm('確定刪除這筆紀錄？')) run(() => onDelete(record))
  }

  return (
    <div className={open ? 'sheet open' : 'sheet'} onClick={onClose}>
      <div className="sheet-card" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <h3>{isEdit ? '編輯紀錄' : '新增紀錄'}</h3>

        {/* 支出/收入切換（編輯時鎖定 —— 換類型等於換資料表，請刪掉重記） */}
        <div className="chips wrap" style={{ marginBottom: 10 }}>
          <button className={type === 'expense' ? 'chip active' : 'chip'} disabled={isEdit}
                  onClick={() => setType('expense')}>💸 支出</button>
          <button className={type === 'income' ? 'chip active' : 'chip'} disabled={isEdit}
                  onClick={() => setType('income')}>💰 收入</button>
        </div>

        <input className="note-input" placeholder="項目（例：午餐）"
               value={item} maxLength={60} onChange={(e) => setItem(e.target.value)} />
        {/* inputMode=numeric：手機直接跳數字鍵盤 */}
        <input className="note-input" placeholder="金額" inputMode="numeric"
               value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ''))} />
        <input className="note-input" placeholder="分類（選填，留空交給每週 AI 分類）"
               list="cat-options" value={category} maxLength={20}
               onChange={(e) => setCategory(e.target.value)} />
        <datalist id="cat-options">
          {(knownCats || []).map((c) => <option key={c} value={c} />)}
        </datalist>

        {err && <p className="sheet-err">⚠️ {err}</p>}

        <div className="sheet-actions">
          <button className="btn primary" disabled={busy} onClick={submit}>
            {busy ? '…' : isEdit ? '✅ 儲存' : '✅ 新增'}
          </button>
          {isEdit && (
            <button className="btn danger" disabled={busy} onClick={removeRecord}>🗑️ 刪除</button>
          )}
          <button className="btn" disabled={busy} onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
