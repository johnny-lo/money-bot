// 上傳前在手機端先縮圖：手機原圖動輒 3-5MB，縮到長邊 1280px + JPEG 壓縮
// 通常剩 200-400KB —— 上傳快、之後清單載入也快。
// 任何一步失敗（瀏覽器不支援該格式如 HEIC）就退回原檔，後端照收。
export async function shrinkImage(file, maxPx = 1280, quality = 0.82) {
  try {
    const bmp = await createImageBitmap(file)
    const scale = Math.min(1, maxPx / Math.max(bmp.width, bmp.height))
    // 已經夠小就不重壓（重壓只會越壓越糊）
    if (scale === 1 && file.size < 600 * 1024) return file
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bmp.width * scale)
    canvas.height = Math.round(bmp.height * scale)
    canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
    if (!blob) return file
    return new File([blob], 'photo.jpg', { type: 'image/jpeg' })
  } catch {
    return file
  }
}
