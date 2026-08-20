// 跟後端要資料的小工具。
//
// 認證兩層：
// 1. 短效 token（網址列 ?token=...，30 分鐘）＝從 Discord 拿到的「邀請函」
// 2. 長效裝置 token（localStorage）＝第一次用邀請函開啟時跟後端換發，
//    之後 API 全走 X-Device-Token header → 釘在主畫面的 PWA 不用一直回 Discord 拿連結

const DEVICE_TOKEN_KEY = 'deviceToken'

function shortTokenFromUrl() {
  return new URLSearchParams(window.location.search).get('token') || ''
}

// 確保手上有可用憑證。回傳 {device, short} 其中一個有值。
export async function ensureAuth() {
  const device = localStorage.getItem(DEVICE_TOKEN_KEY)
  if (device) return { device, short: '' }

  const short = shortTokenFromUrl()
  if (!short) return { device: '', short: '' }   // 兩者皆無 → 呼叫端顯示「請從 Discord 開啟」

  // 用短效 token 換發長效裝置 token（label 帶上裝置簡述，之後好認是誰的手機）
  try {
    const label = encodeURIComponent(navigator.userAgent.slice(0, 100))
    const res = await fetch(`/api/device-token?token=${short}&label=${label}`, {
      method: 'POST',
    })
    if (res.ok) {
      const data = await res.json()
      localStorage.setItem(DEVICE_TOKEN_KEY, data.token)
      // 把一次性 token 從網址拿掉：之後加入主畫面/分享網址都不會帶到它
      const url = new URL(window.location)
      url.searchParams.delete('token')
      window.history.replaceState({}, '', url)
      return { device: data.token, short: '' }
    }
  } catch { /* 換發失敗就退回用短效 token，本次仍可瀏覽 */ }
  return { device: '', short }
}

async function authedFetch(path, { method = 'GET', body = null, json = null } = {}) {
  const { device, short } = await ensureAuth()
  if (!device && !short) {
    throw new Error('沒有有效憑證，請回 Discord 用 /美食地圖 重新開啟一次。')
  }

  const headers = {}
  let url = path
  if (device) headers['X-Device-Token'] = device
  else url += (path.includes('?') ? '&' : '?') + 'token=' + short

  // json 給一般寫操作；body（FormData）給檔案上傳——FormData 不能自己設 Content-Type，
  // 要讓瀏覽器帶 multipart boundary
  if (json !== null) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }

  const res = await fetch(url, { method, headers, body })

  // 裝置 token 被撤銷/DB 清掉 → 清掉重來，下次用新邀請函自動再換發
  if (res.status === 401 && device) {
    localStorage.removeItem(DEVICE_TOKEN_KEY)
    throw new Error('這台裝置的授權已失效，請回 Discord 用 /美食地圖 重新開啟一次。')
  }

  const text = await res.text()
  if (!res.ok) {
    let detail = res.status
    try { detail = JSON.parse(text).detail || res.status } catch { /* 非 JSON 就用狀態碼 */ }
    throw new Error('載入失敗：' + detail)
  }
  try {
    return JSON.parse(text)
  } catch {
    throw new Error('資料格式錯誤：伺服器沒有回 JSON，請重新整理')
  }
}

// 拿全部店家（一次抓完，篩選在前端做 → 切 filter 是瞬間的，不用再連線）
export async function getPlaces() {
  return authedFetch('/api/food/places')
}

// 標去過（可帶評分 1-5 / 一句心得）。回 {place}。
export async function markVisited(placeId, rating, note) {
  return authedFetch(`/api/food/places/${placeId}/visited`, {
    method: 'POST',
    json: { rating: rating || null, note: note || null },
  })
}

// 上傳一張店家照片。回 {photo: {id,url,source}}。
export async function uploadPhoto(placeId, file) {
  const form = new FormData()
  form.append('file', file)
  return authedFetch(`/api/food/places/${placeId}/photos`, { method: 'POST', body: form })
}

// 刪一張照片。
export async function deletePhoto(photoId) {
  return authedFetch(`/api/food/photos/${photoId}`, { method: 'DELETE' })
}

// ── 消費（沿用現有報表/CRUD API）─────────────────────────────

// 某月流水帳。回 {records: [{id,type,item,amount,category,created_at}]}（新到舊）。
export async function getLedger(year, month) {
  return authedFetch(`/api/report/ledger?year=${year}&month=${month}`)
}

// 新增一筆。payload = {type:'expense'|'income', item, amount, category?}
export async function createRecord(payload) {
  return authedFetch('/api/record', { method: 'POST', json: payload })
}

// 修改一筆（只送有改的欄位也行）。
export async function updateRecord(type, id, payload) {
  return authedFetch(`/api/record/${type}/${id}`, { method: 'PUT', json: payload })
}

// 刪一筆。
export async function deleteRecord(type, id) {
  return authedFetch(`/api/record/${type}/${id}`, { method: 'DELETE' })
}

// ── 食譜 ─────────────────────────────────────────────────────

export async function getRecipes() {
  return authedFetch('/api/recipes')
}

export async function renameRecipe(id, name) {
  return authedFetch(`/api/recipes/${id}`, { method: 'PUT', json: { name } })
}

export async function deleteRecipe(id) {
  return authedFetch(`/api/recipes/${id}`, { method: 'DELETE' })
}

// ── 歷史影片 ─────────────────────────────────────────────────

export async function getVideos() {
  return authedFetch('/api/videos')
}

export async function updateVideo(id, payload) {
  return authedFetch(`/api/videos/${id}`, { method: 'PUT', json: payload })
}

export async function addVideoTag(id, tag) {
  return authedFetch(`/api/videos/${id}/tags`, { method: 'POST', json: { tag } })
}

export async function removeVideoTag(id, tag) {
  return authedFetch(`/api/videos/${id}/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' })
}

export async function deleteVideo(id) {
  return authedFetch(`/api/videos/${id}`, { method: 'DELETE' })
}
