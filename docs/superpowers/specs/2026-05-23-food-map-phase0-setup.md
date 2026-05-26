# 美食地圖模組 — Phase 0 事前設定清單

> 寫任何 code 前，照這份逐項打勾做完。全部是「手動設定 + 填 env」，不動程式。
> 完成後把 `.env` 填好通知我，我再進 writing-plans 拆 Phase 1。
> 對應設計：`2026-05-23-food-map-module-design.md`

MVP 階段只需要：**1 個 Discord 頻道**（`#美食輸入`）＋ **1 把 Google Places 後端 key**。
（地圖用的 browser key、YouTube key 都**不是**這階段要做的。）

---

## A. Discord 頻道

- [ ] **A1. 建立 `#美食輸入` 文字頻道**（建議放在現有「記帳機器人」分類底下）
- [ ] **A2. 開啟開發者模式**：Discord → 使用者設定 → 進階 → 「開發者模式」開
- [ ] **A3. 取得 `#美食輸入` 的 Channel ID**：右鍵該頻道 → 複製頻道 ID → 記下來
- [ ] **A4. 確認 `#記帳` 的 Channel ID**：同樣右鍵複製
  - 若 `.env` 已有 `DISCORD_RECORD_CHANNEL_ID` 就核對一致；沒有就補上
  - ⚠️ 沒設這個的話，圖片記帳會退回「任何頻道都記」的舊行為（不會壞，但不會分流）

> 機器人需要能讀這頻道的訊息與附件——它用既有 Bot Token，已在你的伺服器內，通常不必額外授權；若收不到訊息再檢查頻道權限。

---

## B. Google Cloud — Places API 後端 key

> 大致路徑（Google 介面偶爾微調，找關鍵字即可）。

- [ ] **B1. 建立/選擇專案**：<https://console.cloud.google.com/> → 上方專案選單 → 新增專案（例如 `money-bot-food`）
- [ ] **B2. 綁定帳單帳號**：左選單 Billing → 連結一張信用卡
  - 免費額度內不扣款；這步只是 Google 規定要有帳單帳號
- [ ] **B3. 啟用 API**：APIs & Services → Library → 搜尋並啟用 **「Places API (New)」**
  - 雷點摘要用的 Place Details 也屬於這個 Places API (New)，啟用一個就夠
- [ ] **B4. 建立 API key**：APIs & Services → Credentials → Create credentials → API key → 複製
- [ ] **B5. 限制這把 key**（重要，降風險）：點該 key → Edit
  - **API restrictions** → Restrict key → 只勾 **Places API (New)**
  - **Application restrictions** → 先設 `None`（後端用、藏在伺服器；靠下面的配額+預算當護欄）
- [ ] **B6. 設配額硬上限**：APIs & Services → 該 API → Quotas → 把每日請求數上限設低（例如 **50/日**）
  - 這樣就算程式寫錯迴圈也打不爆免費額度
- [ ] **B7. 設預算警示**：Billing → Budgets & alerts → 建預算 **US$1**，超過就 email 你
- [ ] **B8. 記下這把 key** → 之後填 `GOOGLE_PLACES_SERVER_KEY`

> 注意：這把是**後端 key**，只會放在伺服器/`.env`，**絕不**出現在任何網頁 HTML。

---

## C. 填進 env（兩個地方都要）

- [ ] **C1. `.env` 新增 / 確認：**
  ```
  FOOD_INGEST_CHANNEL_ID=（A3 的 ID）
  DISCORD_RECORD_CHANNEL_ID=（A4 的 ID，已存在就核對）
  GOOGLE_PLACES_SERVER_KEY=（B8 的 key）
  ```
- [ ] **C2. `docker-compose.yml` 的 `app.environment:` 補對應三行**（用 `${VAR}` 帶入）
  - 教訓：先前 channel ID 只放 `.env` 沒進 compose，導致容器內 `os.getenv()` 拿不到 → 靜默失敗
  - 這步等實作時我會幫你一起改，但 key/ID 要你先備好

> 既有的 `GEMINI_API_KEY`（截圖辨識用）與 codex（已裝）沿用，不必重弄。

---

## D. 不是這階段要做的（先別碰）

- ❌ `GOOGLE_MAPS_BROWSER_KEY`（地圖前端 key）→ Phase 2 地圖階段才開
- ❌ `YOUTUBE_API_KEY` → Phase 3 連結階段才開（且選做）
- ❌ Maps JavaScript API 啟用 → 地圖階段才需要

---

## 完成標準

- [ ] `#美食輸入` 頻道存在、ID 已拿到
- [ ] Places API (New) 已啟用、後端 key 已建立並限制好 API + 配額 + 預算
- [ ] `.env` 三個值都填好

做完跟我說，我會先用你的 `GOOGLE_PLACES_SERVER_KEY` 做一次連線測試（確認查得到店家），再進 Phase 1 實作計畫。
