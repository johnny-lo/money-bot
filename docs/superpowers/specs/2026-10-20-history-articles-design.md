# 歷史頻道也收文章網頁

## 現況

`#📜-歷史教學` 頻道與 PWA 歷史分頁原本是「歷史教學影片」圖書館：`video/ingest.from_url` 對每個連結呼叫
`food.extract.from_url`（YouTube／IG／TikTok／FB 走 yt-dlp，其他網站只抓 og:title＋og:description），
再用 codex 判主題書架＋標籤，存 `history_videos`。

文章網頁其實走得進來（`platform="other"`），但：

- 只餵 AI og 標題和描述，內文一個字都沒有，主題判得粗；
- 沒有 og:title 的網站直接「抽不到影片標題」失敗；
- AI 提示寫「這是一支歷史教學影片」；Discord 卡片、說明、PWA 文案都只講影片，看不出哪則是文章。

## 決定（2026-10-20，本人在 Claude Code 要求）

| 題目 | 決定 |
|---|---|
| 存哪裡 | 同一張 `history_videos`、同一套主題書架與標籤；不另開表、不加欄位 |
| 影片還是文章 | 由 `platform` 推：youtube／instagram／tiktok／facebook＝影片，其餘（含 threads、other）＝文章；`repo.to_dict` 多回 `kind` |
| 文章抓什麼 | 文章專用抽取（`video/` 裡，不動 `food.extract`——美食模組共用它）：標題＝og:title，沒有就 `<title>`；描述＝og:description 或 meta description；內文＝去掉 script／style／nav／header／footer 後，優先 `<article>`、其次 `<main>`、再其次所有 `<p>` 的文字，壓空白後取前 3,000 字。用一般瀏覽器 UA 抓；抓不到內文仍用標題＋描述分類 |
| AI 提示 | 依種類寫「影片」或「文章」，規則（單一主題書架、3～5 個跨主題標籤）不變 |
| 縮圖 | 這次不做（要加欄位存 og:image）；文章卡片沒有縮圖時顯示 📄 |
| 介面文案 | Discord 卡片標題與 PWA 依種類顯示 🎥 影片／📄 文章；數量、空狀態、說明文字改成影片與文章都適用 |
