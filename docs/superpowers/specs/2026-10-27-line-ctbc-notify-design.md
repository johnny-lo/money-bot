# 中信 LINE 刷卡通知即時進刷卡比對 — 設計

日期：2026-10-27　狀態：設計中，待 builder check 與本人核可

## 為什麼

中信的即時刷卡通知只推到本人個人 LINE 裡的官方帳號「中國信託」。Gmail 只有中信**月帳單**，最晚約 40 天才到
（目前 `card_charges` 的中信資料只到 10/10），而且帳單上的中文店名是圖片，要靠讀圖。結果是刷卡比對對中信
永遠慢一個月、店名靠猜。

本人要的是：中信一推通知，程式就讀到、拆出金額／時間／卡號／店名，幾分鐘內寫進 `card_charges`，週日清單
就有完整的中信刷卡。本人也想「不被 LINE 的程式綁住」：自己手上有一份資料，自己決定怎麼用。這次只做中信，
之後的「AI 助理」項目會用到同一份 LINE 資料。

## 目標

1. 中信消費通知在分鐘級寫進 `card_charges`（新來源 `ctbc_line`）。
2. 下一期中信月帳單裡的同一筆刷卡，和 LINE 那筆合成一筆：不重複列進清單、不重複配對。
3. 上線時回補 LINE 伺服器還留著的中信通知（10/14 起，約 18 筆）。
4. 被 LINE 踢掉、或通知拆不出來時，Discord 告訴本人發生什麼、要做什麼。

## 不做

- 不即時推 Discord：週日清單照舊（本人選的）。
- 不讀其他聊天室、其他銀行；不傳任何 LINE 訊息、不送已讀、不改 LINE 設定。
- 不做 AI 助理／MCP（另一個項目）。
- 不處理 LINE Chrome 版可能停止服務的問題（本人：先不管這個風險）。

## 反目標（就算功能會動，出現這些也算失敗）

- 同一筆刷卡在週日清單出現兩次（LINE 一筆、帳單一筆）。
- 其他聊天室的內容被存進 DB 或寫進 log。
- LINE 的 session 檔出現在 money-bot 容器、log、repo 或環境變數裡。
- 程式主動對 LINE 做寫入動作，或高頻呼叫 API（拉高封號風險）。
- listener 默默停了，一週以上沒人發現。

## 已定決策

| 題目 | 決定 |
|---|---|
| 讀 LINE 的方式 | OkLine（非官方，模仿 LINE Chrome 擴充功能 3.7.2 的協定）。本人知道這違反 LINE 條款、帳號可能被限制，接受 |
| Chrome 裡的 LINE | 試做的新登入把本人 Chrome 裡的 LINE 擠掉了，本人接受；之後 Chrome 不再登入 LINE（再登會把程式踢掉） |
| 通知怎麼拆 | 一般程式拆；拆不出來才交給 codex，模型用 sol，不用 astra（容器目前只能用 `gpt-5.6-sol`，見 watchdog 一節） |
| Discord 即時推 | 不推，照每週日清單 |
| 回補 | 補 LINE 上還留著的（10/14 起） |

## 試做實測事實（2026-10-27，唯讀）

- **OkLine 2.9.2**（GitHub `NiceDayZc/OkLine` commit `2e3437977368802edcc2219798b9d5333665ebca`，2026-09-13）。審過：
  - Python 只用 `requests` 連 LINE 網域：`line-chrome-gw.line-apps.com`、`legy-jp/legy-backup.line-apps.com`、
    `obs.line-apps.com`、`*.line-scdn.net`。base URL 全來自 `okline/endpoints.py` 常數。
  - `okline/ltsm/ltsm_bridge.js` 只用 `fs`/`path`/`readline`/`crypto`，不連網。
  - `ltsm.wasm`（sha256 `58bb4e189ab9bbd7d72ed415258da36afd50e306cb019bab75329d4f5f1b65b3`）與 `ltsmSandbox.js`
    （sha256 `5c66cba945cc039d817e87fef2aa1e28c8adb7be0f94fca5b95bb6bcf5a07c94`）和本機 LINE 擴充功能 3.7.2 的原檔逐位元相同。
  - 需要 Node 18+（money-bot image 已有 Node v20）。
- **登入**：`okline login` 畫 QR → 手機掃 → 手機確認 PIN。session 檔（access/refresh token、certificate、
  E2EE keychain）存在主機 `~/.config/money-bot/line-spike/tokens.json`（0600，目錄 0700）。refresh 自動；用
  `OkLine.from_tokens_file()` 載入的話，refresh 後的新 token 會寫回檔案。refresh 被拒（gateway 10201）＝被踢，要重新登入。
- **同一個帳號只能有一個 Chrome 版 session**：新登入讓本人 Chrome 裡的 LINE 被登出。本人另外實測：Chrome 版和
  LINE 電腦版是不同的登入位置，互不影響（開電腦版不會踢掉 listener）。
- **找聊天室**：中信官方帳號的 displayName 正好是「中國信託」。另有一個個人聯絡人的名字也含「中國信託」，不是要找的，
  所以比對要用完全相等，不能用「包含」。1 對 1 聊天室的 message box id 就是對方的 mid。
- **歷史**：`get_recent_messages(mid, 200)` 只回 35 則（10/14 起），伺服器端就留這些。`get_previous_messages`
  只回傳 end message 本身，**往回翻會無限迴圈**（試做踩到，跑了 24 分鐘才停掉）。
- **35 則的組成**：「🔔LINE Pay聯名卡消費通知🔔」18 則、「🔔即時入帳通知🔔」4 則（錢進帳戶，不是消費）、文字廣告 11 則、
  「中信交易優惠券到期通知」1 則、沒有 ALT_TEXT 的 Flex 1 則。
- **消費通知的樣子**：`contentType` 22（FLEX），`contentMetadata.ALT_TEXT` 含「消費通知」，`FLEX_JSON` 是 carousel。
  第一個 bubble 的 body 依序是：

  ```
  text  刷卡通知
  text  NT$59
  box(horizontal)  text 卡末四碼：   text 1234
  box(horizontal)  text 交易時間：   text 2026/10/27  13:01      ← 日期和時間之間是兩個空白
  實體店：  box(horizontal)  text 商店名稱：  text ＸＸ炸雞－某某店   ← 全形
  網路消費：box(horizontal)  text 交易類型：  text 非實體卡交易
           box(horizontal)  text 商店類型：  text 居家/修繕/3C家電
  text  *商店名稱僅供參考，實際以帳單為準
  text  …回饋說明、廣告…
  ```

  其餘 bubble 都是廣告。18 則消費通知的版型：實體店 14、網路消費（交易類型＋商店類型）2、**海外商店 2**。
  海外商店的版型在金額下面多一組 `外幣金額：` + `TWD 999.99`（幣別碼＋兩位小數），免責文字變成
  「*商店名稱及台幣換算約當金額僅供參考，實際以帳單為準」——也就是說這時 `NT$` 只是**換算的約當金額**，
  帳單上的台幣金額可能不同（匯率、國外交易服務費），用它去跟帳單合併會合不起來。
- **卡號**：有 LINE 通知的是中信主力卡（`card_charges` 已有 1058 筆它的 `ctbc_statement`，最晚 10/10）；另一張中信卡
  沒看到 LINE 通知。真實卡號、店名、金額不寫進 repo（repo 是公開的）。
- **分期**：中信帳單到目前只有 3 筆分期（店名含「分期NN-MM」），都還是 unmatched。分期消費的 LINE 通知長怎樣沒看過。

## 架構

### 新 compose service `line`（container `money-line`）

- 用衍生的 `money-line` image（`FROM money-bot`，見下）；command `python -m lineinbox.listener`；`restart: unless-stopped`。
- volumes：`.:/app`（live-mount，跟 money-bot 同一份程式）、`${HOME}/.config/money-bot/line:/data`（rw，
  因為 refresh 會寫回 session 檔）。
- secrets：只給 `database_url`。**不掛 `~/.codex`、不給 Discord token、不給其他 secrets。**
- 以主機使用者的 uid/gid 執行：session 檔寫回後仍屬於本人、保持 0600。
- 為什麼要獨立一個容器：money-bot 裡的 codex 以 `danger-full-access` 執行，讀得到容器內任何檔案，而 session 檔等於
  整個 LINE 帳號加上解密金鑰，不能放進去。另外，LINE 斷線或 Node 子程序出事也不會拖垮 webhook 和 Discord bot。
- **OkLine 的安裝來源**：PyPI 上最新只有 2.7.0（2026-06），沒有審過的 2.9.2。所以直接從 GitHub 裝**審過的那個
  commit**（`2e3437977368802edcc2219798b9d5333665ebca`），git commit SHA 本身就鎖定了內容。build 時再驗兩個大檔的
  sha256（上面兩個值），對不上就讓 build 失敗。（主線的判斷：這就是審過的原始碼，比 PyPI 上沒審過的版本更準。）
- **用衍生 image，不重 build money-bot**：新增 `money-line` image＝`FROM money-bot` 再裝 OkLine（`--no-deps`；它要的
  `requests`、`cryptography` money-bot image 已經有）與 `qrcode==8.2`（登入時畫 QR）。不動 `requirements.txt`，
  money-bot image 也不用重 build——重 build 會把沒鎖版本的套件一起升級（AGENTS.md 的 SQLAlchemy 2.1 事故）。
  money-bot 之後若重 build，`money-line` 也要跟著重 build（它疊在上面）。
- **不能把 OkLine 放進 repo**：repo 在 GitHub 上是公開的，`ltsm.wasm`／`ltsmSandbox.js` 是 LINE 的專有程式。
  之後升級是刻意的動作：換 commit 要重審、重算兩個 hash。

### 新模組 `lineinbox/`（LINE 收件匣：只收被監看的官方帳號）

```
lineinbox/
  config.py    被監看帳號（displayName「中國信託」→ 來源鍵）、session 路徑 /data/tokens.json、
               心跳／重連參數、codex 備援模型（先用 "gpt-5.6-sol"）
  flex.py      純函式：Flex JSON → 依出現順序的 text 串列（走 header/hero/body/footer/contents）
  repo.py      line_messages 的唯一寫入咽喉點（以 LINE message id 去重）＋ listener 狀態
  listener.py  money-line 的主程式：開機補讀 → 長連線收新訊息 → 心跳 → 被踢就停
  watchdog.py  money-bot 排程呼叫：codex 備援解析、Discord 告警
```

通知的 parser 放在 `cardrecon/parse.py`（`parse_ctbc_line`），跟其他刷卡 parser 放一起。

### 新表 `line_messages`（新表，`create_all` 自動建）

每則被監看帳號的訊息存一列，不只消費通知：量很小（一天約 2 則），之後 AI 助理也用得到。內容大致是：
LINE message id（唯一）、來源鍵、訊息時間（LINE `createdTime`，換台北時間）、ALT_TEXT、contentType、攤平後的文字、
種類（消費通知或其他）、處理狀態、寫進 `card_charges` 的哪一列、錯誤訊息。

消費通知的判定：ALT_TEXT 含「消費通知」，或攤平後第一段文字是「刷卡通知」。

**只存被監看帳號的訊息。** 長連線收到的其他聊天室訊息在記憶體裡就丟掉，不存、不 log 內容。

### 寫進 `card_charges`

- `Charge(source="ctbc_line", line_no=0, …)`。`message_id` 用 `"line:" + LINE message id`，跟 Gmail 的 id 分開，不會撞。
- 刷卡日與時間取通知文字裡的「交易時間」，不取訊息送達時間。
- `merchant`：實體店用「商店名稱」。網路消費只有「商店類型」，清單上要看得出商店類型，等帳單給出真正店名再換掉。
- 一律經過 `cardrecon/repo.py` 寫入，合併規則也放在那裡。

### 合併規則：LINE ↔ 中信月帳單

**不變式：同一筆實際刷卡，`card_charges` 裡只有一列會被列進清單、會被拿去配發票。**

- 判斷同一筆：卡號末四碼相同、金額相同、刷卡日相同；找不到再放寬到 ±1 天。同一個鍵有好幾筆時（例如同一天刷了兩次
  NT$55），照時間／行號順序一對一配。
- **後到的那一列不另外算一筆**：用新狀態 `merged` 存下來，保留它自己的 (message_id, line_no) 身分，這樣每週重讀
  同一封帳單時不會再被插入一次；它要指回先到的那一列。
- **先到的那一列補上缺的欄位**：LINE 列補帳單的入帳日；帳單列補 LINE 的時間和店名。店名衝突時，LINE 的實體店名
  優先，因為帳單店名是讀圖來的，可能讀錯；LINE 只有商店類型時，用帳單的店名。
- 先到那一列的 status、matched_key、batch 都不動：已配對、已忽略、已補記的維持原狀。
- `merged` 列不能出現在 `pending`、`unlisted`，也不能被 `hints` 的歷史統計和 `used_group_keys` 算進去。
- 帳單有、LINE 沒有的（通知門檻以下，或 listener 斷線那段）照舊算一筆。LINE 有、帳單沒有的（例如取消掉的預先授權）
  也照舊算一筆，本人在清單上忽略就好。
- **分期、請款金額跟授權金額不同的刷卡**（飯店、加油預授權等）：金額對不上就不合併，兩邊照舊各算一筆，本人在清單上處理。
  分期到目前只有 3 筆，第一版不另外處理（主線的判斷）。
- 永豐和其他來源不受影響。
- **合併的可見度**：合併自動進行，週日刷卡比對的卡片上顯示「本週 LINE↔帳單合併幾筆」。上線時兩邊資料沒有重疊
  （帳單到 10/10、LINE 從 10/14 起），第一次真的合併要等 11 月中下旬那期中信帳單；那次由主線跟本人一起確認合對了，
  這個項目才算完成（主線的判斷）。合併要能還原：`merged` 列保留自己的身分與指向，合錯可以拆回來。

### 比對

- `cardrecon.match` 本來就會用刷卡時間（±10 分鐘）配發票。中信帳單沒有時間，LINE 有，所以配得更準。
  週日 pipeline 的 pending → match 會自然處理 `ctbc_line` 列，比對邏輯不用改。
- `LIST_LAG_DAYS=3` 不變：週日清單列到 3 天前為止，等發票補拓追上。

### listener 行為（`money-line`）

1. 開機：載入 session → 用 displayName「中國信託」找 mid。找不到或有好幾個 → 狀態記為錯誤並停下，不猜。
2. 補讀：`get_recent_messages(mid, 200)`，冪等寫進 `line_messages`。**第一次開機的補讀本身就是回補**
   （伺服器只留 10/14 起），不另寫回補程式。**不往回翻頁**（見上面的坑）。
3. 長連線：接 OkLine 的即時 operation feed，只處理被監看 mid 傳來的新訊息。
4. 斷線：指數退避重連（例如 5 秒起、上限 10 分鐘），每次重連前先補讀一次。
5. 心跳：定期更新 listener 狀態（最後成功時間、最後錯誤、目前狀態：正常／被踢／錯誤）。
6. 被踢（refresh 被拒、`LineAuthError`）：狀態記為被踢，**停止重試**。一直撞登入會更像機器人，等人重新登入。
   容器不能變成 crash loop。
7. 拆得出來的消費通知，直接寫 `card_charges`。拆不出來的標成「等 codex」，由 money-bot 處理，因為 money-line 沒有 codex。

### money-bot 端 watchdog（APScheduler，例如每 30 分鐘）

1. **codex 備援**：「等 codex」的消費通知 → `codex_cli.codex_text(prompt, model=<sol>, schema=…)`。
   實測（2026-10-27）：容器裡的 codex 0.154.0 用 ChatGPT 帳號時 `gpt-6.1-sol`、`gpt-6-sol` 都回 `model_not_found`，
   只有 `gpt-5.6-sol` 可用；主機的 codex 0.164.0 可以用 `gpt-6.1-sol`。所以模型做成設定常數，先用 `gpt-5.6-sol`；
   要換 `gpt-6.1-sol` 得先把 Dockerfile 的 `CODEX_VERSION` 升到 0.164.0 並重 build（另一件事，要跟本人說）
   → 驗證（金額 > 0、卡號 4 碼、刷卡日在訊息時間 ±1 天內）→ 寫 `card_charges`。還是失敗 → 標成看不懂，
   發一張 Discord 卡附上通知文字，讓本人看。
2. **listener 告警**：狀態是被踢，或心跳超過 1 小時沒更新 → Discord 告警**一次**，恢復前不重發。內容要寫清楚重新登入
   的步驟（例如 `docker compose run --rm line okline login --save /data/tokens.json`，再 `docker restart money-line`；
   實際指令由 builder 確認可用）。
3. 頻道用 `DISCORD_INVOICE_CHANNEL_ID`，跟刷卡比對同一個。
4. 週日刷卡比對的卡片上加一行：本週 LINE 收到幾筆中信刷卡通知、listener 目前狀態。這樣就算 watchdog 自己也壞了，
   一週內也看得出異狀。

### `parse_ctbc_line`（純函式，單元測試）

- 輸入：攤平後的文字串列。
- 金額：第一個 `NT$<數字與逗號>` → int。
- 卡號：「卡末四碼：」的下一段 → 4 碼數字。
- 時間：「交易時間：」的下一段 → `YYYY/MM/DD` + 空白（數量不固定）+ `HH:MM` → 刷卡日與 `"HH:MM"`。
- 店名：「商店名稱：」的下一段。網路消費：「交易類型：」「商店類型：」的下一段。
- 金額、卡號、時間任一個缺 → 回 None，交給 codex。
- 有 `外幣金額：` 這一組（海外商店，不論幣別碼是不是 TWD）→ 不建刷卡，記成非台幣，等帳單的台幣金額
  （這時的 NT$ 是約當金額，見實測事實）。codex 備援也不能把外幣或約當金額當台幣寫進去。
- 測試 fixture 用**合成資料**：結構相同，但金額、店名、卡號都換掉。repo 在 GitHub 上，真實刷卡內容不進 repo。
  主線會在計畫的第一步，從試做存下的真實訊息做出去識別化的 fixture。

### 上線與搬家

- session 檔從 `~/.config/money-bot/line-spike/` 搬到 `~/.config/money-bot/line/`，不用重新掃碼。試做存下的訊息檔
  （含聊天內容）刪掉，`okline-spike` image 刪掉。
- 文件：README（功能）、CODEBASE（檔案地圖、`line_messages` 表、排程、新 service）、AGENTS.md（坑：往回翻頁會無限
  迴圈；同帳號只能有一個 Chrome 版 session；Chrome 136 以後主要設定檔不能開遠端除錯；Chrome 外掛工具打不開擴充功能頁面）。

## 留給 builder

- `line_messages` 的欄位細節與狀態名稱。
- `merged` 列怎麼指回先到的那一列：加欄位（照 `main.py` 的 ALTER 慣例），或用不會被當成發票群組鍵的格式。
- 網路消費的商店類型在清單上怎麼顯示。
- 心跳間隔、退避參數、watchdog 頻率。
- 長連線用 OkLine 的哪個 API。
- 怎麼驗證 PyPI 上的套件就是審過的版本。

## 已知風險（本人知道並接受）

- **LINE 條款**：自動化個人帳號違反 LINE 條款，帳號可能被限制。對策：只讀、不傳、一條長連線、低頻率。
- **Chrome 版停服**：LINE 已公告要停 Chrome 版，日期未定。停了這條就斷，退回只靠月帳單。
- **協定改版**：LINE 一改，OkLine 就可能壞。listener 告警會讓本人知道。
