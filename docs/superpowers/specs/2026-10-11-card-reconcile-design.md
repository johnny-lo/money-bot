# 刷卡比對：找出載具沒記到的消費 — 設計

日期：2026-10-11　狀態：設計已核可，待 review spec

## 目標

從 Gmail 的信用卡消費資料抽出「錢從哪裡出去」，跟 `transactions` 比對，每週把**有刷卡、帳上卻沒有**的消費
推成一張 Discord 清單卡；本人整批核可就補記進帳，個別項目可以忽略（例如其實是她記的、或是退款前的重複授權）。

## 已定決策（plan board 卡片）

| 題目 | 決定 |
|---|---|
| 資料範圍 | 納入加密 PDF；身分證存在 `national_id` secret（已填） |
| 呈現方式 | 每週推清單＋整批補記，可逐筆忽略 |
| 第一版來源 | 只做信用卡：永豐每日消費通知、中信月帳單。收據（Autopass）只用來替刷卡補店名；轉帳、繳費不做 |
| 歷史怎麼處理 | ⏳ 卡片未回，本 spec 先依推薦「只從上線那週開始列，歷史另出一次性報表、不寫入」；若改選，只動〈歷史資料〉一節 |

## 實測事實（2026-10-11，唯讀）

- 永豐 `spendservice@sinopac.com`「永豐銀行信用卡 MM月DD日 消費通知」：106 封，附件 `Sinopac_Service.pdf`，
  密碼＝身分證字號（英文大寫）。每筆：卡別、卡號末四碼、消費日期（月/日，年份取「期間：115/10/08」的民國年）、
  時間、地區、`NT$ 金額`。**沒有店名**。外幣已換算成台幣。
- 中信 `ebill@estats.ctbcbank.com`「中國信託信用卡電子帳單 11509」：19 封，附件 `CTBC_card_Estatement_*.pdf`，
  密碼同上。pypdf 抽出的文字是 `/UNIC0038` 這種字形名，`chr(0x0038)` 即可還原。每筆兩種版型：
  - 同一行：`115/08/05 115/08/07 ACME *STREAMING SUB 450 5678 US TWD 450.00`（英文店名留得住）
  - 兩行：`115/09/06 115/09/09` 換行 `A 160 5678 TW`（中文店名抽不出來；`A`＝行動支付代碼，可能沒有）
- 共解析 1272 筆、0 封失敗：中信兩張卡各 1026、41 筆，永豐一張卡 205 筆。
- `mma@sinopac.com`「DAWHO 交易即時訊息通知--信用卡交易」是**繳卡費**，不是消費 → 永遠排除。
- Autopass `cs@autopass.xyz` 收據內文：`付款成功 80元 某某市路邊停車費 <uuid> … 付款金額 80元 … 付款時間：2026.05.03 09:30`。
  （蝦皮店到店代收款是取貨付現，不走信用卡 → 不做。）
- 用「同金額＋交易日在刷卡日 −1～+3 天」去對 2/22 以來的帳目：配到 227 筆、沒配到 255 筆、金額略。
  配到的大多對上 `source IS NULL` 的舊帳 → **要拿全部帳目去比，不能只比載具1**。
- `GMAIL_ADDRESS` 目前只在 `.env`，沒傳進容器；`national_id` secret 已掛進 money-bot。

## 架構

新模組 `cardrecon/`，照 repo 標準分層（extract / repo / ingest 分開，純函式可單元測試）：

```
cardrecon/
  types.py    資料契約：Charge、Receipt、TxGroup（dataclass，無 I/O）
  parse.py    純函式：PDF 文字 / 信件內文 → Charge / Receipt
  pdf.py      解密 + 抽文字（pypdf），含 /UNICxxxx 還原；回 str 或 None
  gmail.py    IMAP 唯讀抓信 → RawMail
  match.py    純函式：Charge × TxGroup → 配對結果；Receipt → 補店名
  repo.py     card_charges CRUD；upsert 是唯一寫入咽喉點；記帳寫 transactions
  ingest.py   orchestrator：抓信 → 解析 → upsert → 補店名 → 比對 → 回本週清單
discordbot/cardrecon_ui.py   清單卡 + 按鈕 / 下拉（DynamicItem，重啟可接手）
```

### 資料契約（types.py，先寫好，四條平行任務都只依賴它）

```python
@dataclass(frozen=True)
class Charge:
    source: str          # "sinopac_daily" | "ctbc_statement"
    card_last4: str
    charge_date: date
    amount: int          # 台幣整數；只收 > 0（退款/負數由 parser 丟掉）
    line_no: int         # 這筆在該封信裡的序號（0 起），與 message_id 合起來當唯一鍵
    charge_time: str | None = None   # "23:12"（永豐才有）
    post_date: date | None = None    # 入帳日（中信才有）
    region: str | None = None        # "TW" / "US" …
    merchant: str | None = None      # 中信英文店名；其餘 None
    pay_method: str | None = None    # 中信行動支付代碼（"A" 等）

@dataclass(frozen=True)
class Receipt:
    paid_date: date
    amount: int
    merchant: str        # 例：「某某市路邊停車費」

@dataclass(frozen=True)
class TxGroup:
    key: str             # invoice_no，或手記帳 "id<transaction.id>"
    tx_date: date        # 台北時區的 created_at 日期（同張發票取最早）
    amount: int          # 同張發票品項加總（含折扣負數行）

@dataclass(frozen=True)
class RawMail:
    message_id: str
    sender: str
    subject: str
    received: date
    pdf: bytes | None    # 第一個 %PDF 開頭的附件
    text: str            # text/html 去標籤後（或 text/plain）
```

### parse.py（純函式）

- `parse_sinopac(text: str) -> list[Charge]`：年份取「期間：(\d+)/」的民國年＋1911；每筆用正則
  `(正卡|附卡)\s+(\d{4})\s+(\d+)\s*/\s*(\d+)\s+(\d+)：(\d+)\s+(\S+)\s+NT\$\s*(-?[\d,]+)`。
- `parse_ctbc(text: str) -> list[Charge]`：先 `/UNIC([0-9A-F]{4})` → 字元，再逐行比對上面兩種版型。
  跨年由民國年完整日期決定，不用推算。
- `parse_autopass(text: str) -> Receipt | None`：取「付款金額 N元」、「付款時間：YYYY.MM.DD」、
  「付款成功 N元 <店名> <uuid>」的店名。
- 版型不認得 → 回 `[]` / `None`，不丟例外（由 ingest 記成「解析 0 筆」的警告）。

### match.py（純函式）

- `match(charges: list[tuple[int, Charge]], groups: list[TxGroup]) -> dict[int, str]`：
  輸入 (charge_id, Charge)，回 {charge_id: group.key}。規則：
  1. 依刷卡日由舊到新處理；
  2. 候選＝金額完全相同、且 `tx_date − charge_date` 依序為 0、+1、−1、+2、+3 天；
  3. 取第一個還沒被用掉的群組，一對一（一個群組只配一筆刷卡）。
- `enrich(charges: list[tuple[int, Charge]], receipts: list[Receipt]) -> dict[int, str]`：
  只替 `merchant is None` 的刷卡補店名；條件同金額、`paid_date` 與刷卡日差 0～1 天，一對一。
- 呼叫端負責把「已被其他 card_charges 佔用的群組」先排除。

### 資料表 `card_charges`（新表，create_all 自動建）

| 欄位 | 說明 |
|---|---|
| id | PK |
| message_id, line_no | **唯一鍵**（UniqueConstraint）。同一封信重抓不會重複 |
| source, card_last4, charge_date, charge_time, post_date, amount, region, merchant, pay_method | 來自 Charge |
| status | `unmatched` / `matched` / `ignored` / `recorded` / `history` |
| matched_key | 配到的 TxGroup.key（matched / recorded 才有） |
| batch | 列進哪一週的清單卡（週日日期字串 `2026-10-18`）；沒列過為 NULL |
| created_at, updated_at | |

`repo.py` 介面：
- `upsert_charges(db, message_id, charges) -> int`：插入新的；已存在就跳過（不覆蓋 status）。回新增筆數。
- `set_merchant(db, {charge_id: merchant})`、`mark_matched(db, {charge_id: key})`
- `pending(db, until: date) -> list[(id, Charge)]`：status=unmatched 且 charge_date ≤ until
- `used_group_keys(db) -> set[str]`、`load_groups(db, since: date) -> list[TxGroup]`
- `assign_batch(db, ids, batch)`、`batch_items(db, batch) -> list[(id, Charge, status)]`
- `ignore(db, ids)`、`record(db, batch) -> (count, total)`：見〈補記〉。

### gmail.py

- `fetch(sender: str, subject_kw: str, since: date | None) -> list[RawMail]`：
  `select(All Mail, readonly=True)`、`UID SEARCH CHARSET UTF-8 FROM … SUBJECT … [SINCE …]`、`BODY.PEEK[]`。
- 帳號 `os.getenv("GMAIL_ADDRESS")`，密碼 `get_secret("GMAIL_APP_PASSWORD")`；缺任一 → 丟 `RuntimeError`。
- **唯讀守衛測試**：`tests/test_cardrecon_gmail_guard.py` 以原始碼掃描確認 gmail.py 沒有
  `.store(`、`.expunge(`、`.copy(`、`.move(`、`.append(`，且 select 一定帶 `readonly=True`。

### ingest.py

`run_weekly(today: date) -> WeeklyResult`：
1. 各來源抓信：永豐、中信 `since = today − 60 天`（中信月帳單最晚約 40 天後才到）；Autopass 同。
   第一次（表是空的）`since=None` 抓全部 → 見〈歷史資料〉。
2. 解密 → 解析 → `upsert_charges`；解密失敗 / 解析 0 筆的信件數記進結果。
3. `enrich` 補店名（只針對還沒店名的 unmatched）。
4. `load_groups(since = 最早一筆 pending 的日期 − 3 天)`，扣掉 `used_group_keys`，`match` → `mark_matched`。
   每週都重比，因為發票可能晚幾天才同步進來。
5. 本週清單＝`pending(until = today − 3)` 且 `charge_date ≥ LIST_FROM`；`assign_batch(…, batch=today)`。
   留 3 天緩衝，等發票補拓追上。
6. 回 `WeeklyResult(items, total, failed_mails, unparsed_mails)`。

### 歷史資料（依推薦選項；卡片若改選只動這節）

- `cardrecon/config.py`：`LIST_FROM`＝上線當週的週一（上線時由主線填入實際日期並 commit；在那之前測試用 fake 值）。
- 第一次跑時，`charge_date < LIST_FROM` 且沒配到的，status 設成 `history`，不進週卡、不能補記。
- 一次性報表：`docker exec -w /app money-bot python -m cardrecon.report` 把 history 列成 markdown 表
  （日期、卡、金額、地區、店名），依月份小計。只輸出、不寫 DB；檔案存本機給使用者看。

### Discord：清單卡（`discordbot/cardrecon_ui.py`）

- 發在 `DISCORD_INVOICE_CHANNEL_ID`（#🧾-發票通知）。週日一條龍順序改成：
  發票同步 → **刷卡比對** → AI 分類 → 週報 → 月結。
- 本週 0 筆 → 不發卡（有失敗信件時才發一張警告卡）。
- Embed：標題「💳 本週疑似漏記 N 筆，共 $X」；每行 `10/03 永豐1234 US $1,500 店名`；
  超過 4096 字截斷並註明「其餘 M 筆下週再列」（留在 unmatched，不指派 batch）。
- 元件（DynamicItem，custom_id 自帶 batch，bot 重啟不用記憶體狀態）：
  - 下拉 `cardrecon:ignore:<batch>`：多選要忽略的項目（最多 25 個）→ `ignore(ids)`，更新卡片。
  - 按鈕 `cardrecon:record:<batch>`「全部補記」→ `record(batch)`，按完把卡片改成結果並移除元件。
- 只有本人能按：沿用 `AUTOFIX_OWNER_USER_ID`；別人按回 ephemeral 提示。
- `bridge.py` 加 `post_sync(channel_id, embeds, view)`（現有 `post_embeds_sync` 不帶 view）。

### 補記（`repo.record(batch)`）

- 先對該 batch 的 unmatched 再跑一次 match（這週內發票可能剛進來）→ 配到的改 matched、不補記。
- 其餘每筆寫一筆 `transactions`：`item = merchant or f"信用卡消費（{region}）"`、`price = amount`、
  `source = "信用卡"`、`created_at = 台北時間 charge_date + charge_time（沒有就 12:00）`、
  `invoice_no / seller / category = NULL`（下次週日分類會補 category）。
- 同一筆刷卡 status 改 `recorded`、`matched_key = "id<新 transaction.id>"`，同一個 DB transaction 內完成。
- 冪等：重按只處理 status 還是 unmatched 的，第二次是 0 筆。

## 部署變更

- `requirements.txt` 加 `pypdf`、`cryptography`（AES 加密的 PDF 需要）→ **要 rebuild image**。
- `docker-compose.yml` money-bot 的 `environment:` 加 `GMAIL_ADDRESS=${GMAIL_ADDRESS}`（不是機密，帳號而已）。
- `national_id`、`gmail_app_password` secret 已掛好，不用動。
- 文件：README（新功能說明）、CODEBASE（模組、表、排程）、AGENTS（踩到的坑：PDF 字形名、繳卡費要排除）。

## 錯誤處理

| 狀況 | 處理 |
|---|---|
| IMAP 登入失敗 / 缺帳密 | 丟例外；`_weekly_pipeline` 的 try 印出，並發一張「刷卡比對失敗」卡 |
| 單封解密失敗 | 跳過該封，計數進結果，卡片頁尾顯示 |
| 單封解析 0 筆 | 同上（銀行改版的訊號） |
| 補記途中例外 | DB rollback，卡片元件保留可重按 |

## 測試

純單元測試，不連 DB、不出網（照 repo 慣例）：
- parse：合成文字樣本（照實測格式手寫，不放真實消費資料進 repo），涵蓋兩種中信版型、跨年、負數、
  `,` 千分位、無 `A` 代碼、版型不認得回空。
- match：同日、+1、−1、+3、+4（不配）、一對一不重複、已佔用群組、enrich 的 0～1 天。
- model：`__table__.columns` 驗欄位與唯一鍵。
- repo：FakeSession 驗 upsert 不覆蓋 status、record 寫入契約（source、created_at、冪等）。
- gmail 唯讀守衛（原始碼掃描）。
- Discord：`can_act` 類的純函式（本人才能按）；embed 截斷。
- Smoke：`scripts/gmail_probe.sh` 跑 `ingest` 的 dry-run（不寫 DB），比對數字應與本 spec 的實測一致
  （1272 筆、0 失敗）。

## 平行開發切法

`types.py`、`config.py`、model（`card_charges`）先由主線寫好並 commit，作為契約。之後四條獨立任務：

1. **parse + pdf**（parse.py、pdf.py、測試）
2. **match**（match.py、測試）
3. **資料層＋流程**（gmail.py、repo.py、ingest.py、report.py、守衛測試、compose/requirements）
4. **Discord＋排程**（cardrecon_ui.py、bridge.post_sync、main.py 一條龍接線；先對 repo 介面寫，用 fake 測）

1、2 完全獨立；3、4 只依賴上面的 repo 介面簽名。全部 merge 後主線做整合 smoke、文件、上線。

## 不做（YAGNI）

轉帳、繳費、郵局扣款、保費；中文店名的 OCR；她的卡（Gmail 只有你的）；
自動補記（一定要本人按）；即時（每日）推播。
