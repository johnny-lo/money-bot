// 跟後端要資料的小工具。沿用現有的「網址列一次性 token」機制。

function tokenFromUrl() {
  return new URLSearchParams(window.location.search).get('token') || ''
}

// 拿全部店家（一次抓完，篩選在前端做 → 切 filter 是瞬間的，不用再連線）
export async function getPlaces() {
  const params = new URLSearchParams()
  const token = tokenFromUrl()
  if (token) params.set('token', token)

  const res = await fetch(`/api/food/places?${params}`, {
    headers: { 'ngrok-skip-browser-warning': 'true' }, // 跳過 ngrok 免費版的攔截頁
  })
  const text = await res.text()

  if (!res.ok) {
    let detail = res.status
    try { detail = JSON.parse(text).detail || res.status } catch { /* 非 JSON 就用狀態碼 */ }
    throw new Error('載入失敗：' + detail)
  }
  try {
    return JSON.parse(text)
  } catch {
    throw new Error('資料格式錯誤（可能是 ngrok 攔截頁，請重新整理）')
  }
}
