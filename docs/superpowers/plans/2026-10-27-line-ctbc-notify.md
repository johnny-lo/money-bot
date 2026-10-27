# 中信 LINE 刷卡通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讀本人個人 LINE 裡官方帳號「中國信託」推的消費通知，分鐘級寫進 `card_charges`（來源 `ctbc_line`），
跟之後的中信月帳單合成一筆；拆不出來交給 codex（sol），被踢或看不懂時 Discord 告訴本人。

**Architecture:** 新模組 `lineinbox/`（flex 攤平、收件匣 repo、處理流程、OkLine 介面、listener、watchdog）跑在獨立容器
`money-line`（`FROM money-bot` 再裝 OkLine，只掛 `database_url` 與 session 目錄）；刷卡 parser 與合併規則放 `cardrecon/`
（寫入咽喉點 `cardrecon/repo.upsert_charges`）；money-bot 端每 30 分鐘跑 watchdog（codex 備援＋告警）。
Task 0（契約）主線先 commit 到 master；Task 1、2 從那裡各開 worktree **同時**做；兩個都合併後 Task 3、4 再同時做；Task 5 主線收尾。

**Tech Stack:** Python 3.11、SQLAlchemy、OkLine（非官方，GitHub commit `2e3437977368802edcc2219798b9d5333665ebca`）、discord.py、APScheduler、pytest。

**Spec:** `docs/superpowers/specs/2026-10-27-line-ctbc-notify-design.md`

## Global Constraints

- 一切跑在 Docker；worktree 內測試用 `scripts/check_tests.sh`（import 預檢＋全套，`money-bot` image，拋棄式 DB）。
- 測試不連 DB、不出網（`FakeSession` + monkeypatch；model 用 `__table__.columns`）。**測試不得 import `okline`**（`money-bot` image 沒裝）——
  只有 `lineinbox/client.py` 在函式內 import 它。
- 測試樣本只用 `tests/fixtures/ctbc_line/*.json`（合成值）或手寫合成值；repo 是公開的，不得放真實卡號、店名、金額、mid、message id。
- 測試不得走到真的 codex：碰到 `codex_cli` 的測試要把 `codex_cli._codex_exec` 換成會記帳的炸彈（照 `tests/test_cardrecon_ingest.py` 的 autouse 守衛）。
- **不對 LINE 做任何寫入**：不傳訊息、不送已讀、不加好友、不改設定、不登出。`lineinbox/client.py` 只准有讀取函式。
- **其他聊天室的內容不落地**：只處理 `from` 等於被監看 mid 的訊息；不 log 任何訊息文字。
- LINE session 檔只在 `money-line` 容器（`/data/tokens.json`），不進 money-bot、log、repo、環境變數。
- `card_charges.message_id` 用 `"line:" + LINE message id`；`line_no` 一律 0。
- 刷卡日／時間取通知裡的「交易時間」，不取訊息送達時間。
- 有 `外幣金額：` 的通知不建刷卡（狀態 `non_twd`），不論幣別碼。
- codex 備援模型＝`lineinbox.config.CODEX_FALLBACK_MODEL = "gpt-5.6-sol"`（容器 codex 0.154.0 用 ChatGPT 帳號只吃這個 sol）。
- 程式碼註解只寫現況與技術上的「為什麼」；不寫誰決定、哪次討論、試做看到什麼、舊版長怎樣。
- 交件前 `git diff --name-only` 列出改到的 `tests/` 檔，逐檔寫 protected_change claim（為什麼改、改了什麼斷言）。
- 不碰工作目錄裡別人的未 commit 變更：`AGENTS.md`、`plan/log.jsonl`、`.gitattributes`。
- 回覆、commit 訊息用繁體中文；commit 結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## Review Focus

1. **同一天同卡同金額刷兩次**（兩杯 NT$55）＋帳單兩行 → 一對一合併，不能兩行都合到同一筆 LINE 列（Task 2 測試）。
2. **每週重讀同一封中信帳單**（60 天回看）→ 已存在的 (message_id, line_no) 不重插，也不重複合併／不重複補欄位（Task 2 測試）。
3. **listener 斷線重連後補讀到已處理過的訊息** → 不重複寫 `card_charges`、不改既有狀態（Task 3 測試）。
4. **通知版型被中信改掉**（缺金額或時間）→ 進 `needs_codex`，codex 也不行就 `unreadable` 並發 Discord；不能默默丟掉（Task 1、3、4 測試）。
5. **codex 回的東西不可信**：外幣、金額 ≤0、卡號不是 4 碼、日期離訊息時間超過 1 天 → 一律不寫（Task 1 測試）。

---

### Task 0: 契約＋fixture（主線，先 commit 到 master）

**Files:**
- Create: `tests/fixtures/ctbc_line/{store,online,foreign_usd,foreign_twd,deposit}.json`（已做，合成值）
- Create: `lineinbox/__init__.py`、`lineinbox/config.py`、`lineinbox/types.py`、`lineinbox/repo.py`
- Modify: `models.py`（`CardCharge` 加兩欄；新增 `LineMessage`、`LineListenerState`）、`main.py`（ALTER 兩欄）、
  `cardrecon/types.py`（`Charge.merchant_type`）、`cardrecon/repo.py`（`_to_charge` 帶 `merchant_type`）、`cardrecon/config.py`
- Test: `tests/test_cardrecon_model.py`（欄位集合更新）、`tests/test_lineinbox_model.py`、`tests/test_lineinbox_repo.py`

**Interfaces（Produces）:**
- `Charge.merchant_type: str | None = None`（最後一個欄位）；`CardCharge.merged_into`（Integer, nullable）、`CardCharge.merchant_type`（String, nullable）；
  `card_charges.status` 多一個值 `"merged"`。
- `cardrecon.config`：`LINE_SOURCE = "ctbc_line"`、`MERGE_PAIRS = {"ctbc_line": "ctbc_statement", "ctbc_statement": "ctbc_line"}`、`MERGE_SLACK_DAYS = 1`。
- `models.LineMessage`（`line_messages`）：`id`、`message_id`（String, unique, not null；LINE message id，不含前綴）、`source`（String, index）、
  `sent_at`（DateTime，台北時間 naive）、`alt_text`、`content_type`（Integer）、`texts`（Text，JSON 陣列）、`kind`（`"spend"`/`"other"`）、
  `status`（String, index）、`error`、`created_at`、`updated_at`。
- `models.LineListenerState`（`line_listener_state`，只有 id=1 一列）：`id`、`state`、`heartbeat_at`、`last_error`、`alerted`、`updated_at`。
- `lineinbox.config`：`WATCHED = {"中國信託": "ctbc"}`、`CHARGE_ID_PREFIX = "line:"`、`SESSION_PATH = "/data/tokens.json"`、`RECENT_COUNT = 200`、
  `HEARTBEAT_SEC = 300`、`STALE_MIN = 60`、`BACKOFF_START = 5`、`BACKOFF_MAX = 600`、`KICKED_POLL_SEC = 60`、
  `CODEX_FALLBACK_MODEL = "gpt-5.6-sol"`、`FALLBACK_DATE_SLACK_DAYS = 1`、`FALLBACK_PER_RUN = 5`。
- `lineinbox.types`：`InboxMessage(message_id, source, sent_at, alt_text, content_type, texts: list[str], kind)`（frozen dataclass）、
  `ListenerState(state, heartbeat_at, last_error, alerted)`；狀態常數 `PARSED="parsed"`、`NEEDS_CODEX="needs_codex"`、`CODEX_PARSED="codex_parsed"`、
  `UNREADABLE="unreadable"`、`NON_TWD="non_twd"`、`OTHER="other"`；listener 狀態 `STARTING="starting"`、`OK="ok"`、`KICKED="kicked"`、`ERROR="error"`。
- `lineinbox.repo`（line 表的唯一寫入咽喉點）：
  - `exists(db, message_id: str) -> bool`
  - `save_message(db, m: InboxMessage, status: str, error: str | None = None) -> bool`（已存在回 False、不覆蓋）
  - `set_status(db, message_id: str, status: str, error: str | None = None) -> None`
  - `pending_codex(db, limit: int) -> list[InboxMessage]`（狀態 `needs_codex`，依 `sent_at`）
  - `set_state(db, state: str, error: str | None = None, now: datetime | None = None) -> None`（沒有列就建 id=1；`state == OK` 時更新 `heartbeat_at` 並清掉 `alerted`；其他狀態不動 `heartbeat_at`）
  - `listener_state(db) -> ListenerState | None`
  - `mark_alerted(db, kind: str) -> None`
  - `spend_count_since(db, since: datetime) -> int`

- [x] Step 1: fixture（主線已做，已 grep 確認沒有真實資料）
- [ ] Step 2: 寫失敗測試（欄位集合、`save_message` 已存在回 False 且不 add、`set_state` 的 heartbeat 規則）
- [ ] Step 3: 實作上列契約；`main.py` 的 ALTER 迴圈加 `("card_charges", "merged_into", "ALTER TABLE card_charges ADD COLUMN merged_into INTEGER")`、
  `("card_charges", "merchant_type", "ALTER TABLE card_charges ADD COLUMN merchant_type VARCHAR")`
- [ ] Step 4: `scripts/check_tests.sh` 全綠 → commit（連同 spec、本計畫、fixture）

---

### Task 1: 解析（純函式）

**Files:**
- Create: `lineinbox/flex.py`、`lineinbox/fallback.py`
- Modify: `cardrecon/parse.py`（加 `parse_ctbc_line`、`foreign_amount`）
- Test: `tests/test_lineinbox_flex.py`、`tests/test_cardrecon_parse_line.py`、`tests/test_lineinbox_fallback.py`

**Interfaces:**
- Consumes: Task 0 的 `Charge`、`lineinbox.config`、fixture。
- Produces:
  - `flex.texts(node: dict | list) -> list[str]`：依序走 `header`、`hero`、`body`、`footer`、`contents`，收 `type` 為 `text`/`span` 且 `text` 非空的字串；其他欄位（action、url…）一律不收。
  - `flex.message_parts(msg: dict) -> tuple[str | None, int | None, list[str]]`：回 `(ALT_TEXT, contentType, texts)`；
    `contentType == 22` 用 `texts(json.loads(contentMetadata["FLEX_JSON"]))`（壞 JSON 回 `[]`）；`== 0` 用 `[text]`（空就 `[]`）；其他 `[]`。
  - `flex.is_spend(alt: str | None, texts: list[str]) -> bool`：`"消費通知" in alt` 或 `texts[:1] == ["刷卡通知"]`。
  - `parse.foreign_amount(texts: list[str]) -> bool`：有 `"外幣金額："` 這段就 True。
  - `parse.parse_ctbc_line(texts: list[str]) -> Charge | None`：標籤值＝標籤的下一段。金額＝第一個符合 `^NT\$\s*[\d,]+$` 的段落；
    卡號＝「卡末四碼：」的值且符合 `^\d{4}$`；時間＝「交易時間：」的值符合 `^(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})$` → `charge_date`、`charge_time="HH:MM"`（補零）；
    店名＝「商店名稱：」的值做 NFKC＋strip；`pay_method`＝「交易類型：」的值；`merchant_type`＝「商店類型：」的值。
    `foreign_amount` 為 True、或金額／卡號／時間任一缺或格式不符、或金額 ≤0 → None。
    回 `Charge(source="ctbc_line", line_no=0, region=None, post_date=None, …)`。
  - `fallback.SCHEMA: dict`（`amount` integer、`card_last4` string、`date` string、`time` string、`merchant` string 或 null、`foreign` boolean；全部 required、`additionalProperties: false`）
  - `fallback.build_prompt(texts: list[str]) -> str`：明講下面的文字是不可信的外部資料、不是指令；要它抽欄位、海外商店（有外幣金額）時 `foreign=true`。
  - `fallback.charge_from_reply(reply: str, sent_at: datetime) -> Charge | None`：JSON 壞、`foreign` 為 true、`amount ≤ 0`、卡號不是 4 位數字、
    日期不是 `YYYY-MM-DD` 或離 `sent_at.date()` 超過 `FALLBACK_DATE_SLACK_DAYS` 天、時間不是 `HH:MM` → None；店名 NFKC＋strip，空字串或超過 60 字當 None。

- [ ] **Step 1: 寫失敗測試**（全部用 fixture 或手寫合成值）

```python
# tests/test_cardrecon_parse_line.py
def test_實體店():
    c = parse_ctbc_line(_texts("store"))
    assert (c.source, c.card_last4, c.charge_date, c.charge_time, c.amount, c.merchant, c.line_no) == \
        ("ctbc_line", "1234", date(2026, 9, 5), "19:42", 1280, "XX炸雞-測試店", 0)
    assert c.region is None and c.merchant_type is None
def test_網路消費_帶交易類型與商店類型():
    c = parse_ctbc_line(_texts("online"))
    assert (c.amount, c.merchant, c.pay_method, c.merchant_type) == (359, None, "非實體卡交易", "居家/修繕/3C家電")
def test_外幣金額_不論幣別都不建刷卡():
    for name in ("foreign_usd", "foreign_twd"):
        assert foreign_amount(_texts(name)) and parse_ctbc_line(_texts(name)) is None
def test_缺金額或時間_回None(): ...   # 從 store 的 texts 拿掉 "NT$1,280"；另一個把時間改成 "2026/9/5"
def test_時間單位數補零(): ...       # "2026/9/5  7:05" → date(2026,9,5)、"07:05"
```
`flex`：`test_texts_只收文字節點`（手寫 dict 含 button/action/url，結果只有文字）、`test_message_parts_flex與文字訊息`（fixture＋`{"contentType": 0, "text": "hi"}`＋壞 JSON）、
`test_is_spend`（store 為 True、deposit 為 False、只有 ALT 含「消費通知」也 True）。
`fallback`：`test_charge_from_reply_正常`、`test_拒絕外幣`、`test_拒絕卡號與金額`、`test_日期差超過一天拒絕`、`test_壞JSON回None`、`test_prompt_標明不可信`（prompt 含「不可信」）。

- [ ] **Step 2: 跑測試確認失敗** — `scripts/check_tests.sh`，預期新測試 FAIL（找不到函式）
- [ ] **Step 3: 實作**上列函式
- [ ] **Step 4: 全綠** — `scripts/check_tests.sh`
- [ ] **Step 5: commit**

---

### Task 2: 合併（cardrecon）＋清單顯示＋週日摘要

**Files:**
- Modify: `cardrecon/match.py`（`pair_merges`、`merge_updates`）、`cardrecon/repo.py`（`upsert_charges` 合併、`_merge_candidates`、`all_charges`、
  `set_merchant_by_line`、`transaction_fields`、`weekly_line_stats`）、`cardrecon/types.py`（`WeeklyResult` 加欄位）、`cardrecon/ingest.py`、`discordbot/cardrecon_ui.py`
- Test: `tests/test_cardrecon_merge.py`、`tests/test_cardrecon_repo.py`、`tests/test_cardrecon_ui.py`、`tests/test_cardrecon_ingest.py`

**Interfaces:**
- Consumes: Task 0 的 `Charge.merchant_type`、`CardCharge.merged_into`、`cardrecon.config.MERGE_PAIRS/MERGE_SLACK_DAYS`、`lineinbox.repo.listener_state`。
- Produces:
  - `match.pair_merges(incoming: list[tuple[int, Charge]], candidates: list[tuple[int, Charge]], slack_days: int = 1) -> dict[int, int]`：
    incoming 的 key → candidate id。同卡號末四碼、同金額才算；先對日期差 0 全部配一輪，再依序 1…slack_days；一對一；
    同一輪內 incoming 依 `(charge_date, charge_time or "", key)`、candidate 依 `(charge_date, charge_time or "", id)` 排序，各取第一個還沒被用的。
  - `match.merge_updates(canonical: Charge, incoming: Charge) -> dict[str, object]`：兩者一個是 `ctbc_line`（記為 line）、一個是 `ctbc_statement`（記為 stmt）。
    目標值：`charge_time = line or stmt`、`merchant = line or stmt`、`merchant_type = line or stmt`、`pay_method = line or stmt`、`post_date = stmt or line`、`region = stmt or line`
    （`a or b` 指 a 的值非 None 就用 a）；回傳跟 canonical 現值不同的那些欄位。
  - `repo.upsert_charges(db, message_id, charges) -> int`：既有契約不變（已存在的 (message_id, line_no) 跳過、不蓋狀態、一次 commit、回新插入列數）。
    新增：來源在 `MERGE_PAIRS` 的新列，用 `_merge_candidates(db, MERGE_PAIRS[source], charges) -> list[tuple[int, Charge]]`
    （對方來源、`status != "merged"`、沒有被任何列的 `merged_into` 指著、卡號／金額吻合、刷卡日在 incoming 的 ±`MERGE_SLACK_DAYS` 內）跑 `pair_merges`；
    配到的新列以 `status="merged"`、`merged_into=<candidate id>` 插入，並把 `merge_updates(candidate, incoming)` 寫到 candidate 列；沒配到的照舊 `unmatched`。
    candidate 列的 `status`、`matched_key`、`batch` 不動。
  - `repo.all_charges(db)`：排除 `status == "merged"`。
  - `repo.set_merchant_by_line`：寫完店名後，那列若有 `merged_into` 且被指的列店名是空的，也補過去。
  - `repo.transaction_fields(c, brands)`：`item` ＝ 顯示名稱，否則 `信用卡消費（{merchant_type 或 region}）`，兩者都 None 就 `信用卡消費`。
  - `repo.weekly_line_stats(db, since: date) -> tuple[int, int]`：(`source == "ctbc_line"` 且 `charge_date >= since` 的筆數, `status == "merged"` 且 `created_at >= since` 的筆數)。
  - `types.WeeklyResult` 加 `line_charges: int = 0`、`merged: int = 0`、`line_state: str | None = None`；`ingest._run` 在回傳前以 `since = today - 7 天` 填上
    （`line_state` 用 `_soft` 包 `lineinbox.repo.listener_state(db)`，沒有列＝None）。
  - `cardrecon_ui`：`_SRC["ctbc_line"] = "中信"`；`line()` 沒有店名但有 `merchant_type` 時顯示 `（{merchant_type}）`；
    `line_summary(result: WeeklyResult) -> str | None`：`line_state is None` 回 None，否則
    `f"📡 LINE 中信通知：本週 {line_charges} 筆 · 合併帳單 {merged} 筆 · 狀態 {標籤}"`，標籤 `{"ok": "正常", "kicked": "被登出，要重新掃碼", "error": "錯誤", "starting": "啟動中"}`（其他值原樣）；
    `notify_weekly` 在有 `line_summary` 時**一定**另發一張只有這行的 embed（沒有清單頁也發）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_cardrecon_merge.py（純函式）
def test_同卡同額同日_一對一():
    inc = [(0, stmt(55, d=D)), (1, stmt(55, d=D))]
    cand = [(10, line(55, d=D, t="08:00")), (11, line(55, d=D, t="12:00"))]
    assert pair_merges(inc, cand) == {0: 10, 1: 11}
def test_先配同日再配差一天(): ...   # 兩個 candidate 一個同日一個差一天，incoming 同日那筆不能被差一天的搶走
def test_金額或卡號不同_不配(): ...
def test_差兩天_不配(): ...
def test_merge_updates_LINE優先店名時間_帳單補入帳日與地區():
    u = merge_updates(line(500, merchant="A店", t="12:30"), stmt(500, merchant="A店OCR", post=date(2026, 9, 7), region="TW"))
    assert u == {"post_date": date(2026, 9, 7), "region": "TW"}
    u2 = merge_updates(stmt(500, merchant="A店OCR"), line(500, merchant="A店", t="12:30"))
    assert u2 == {"merchant": "A店", "charge_time": "12:30"}
```
`tests/test_cardrecon_repo.py`：`test_upsert_帳單行配到LINE列_存成merged並補欄位`（monkeypatch `_merge_candidates` 回一個 LINE 候選、`_by_ids` 回對應 SimpleNamespace；
斷言新列 `status == "merged"`、`merged_into == 候選 id`、候選列多了 `post_date`、候選 `status` 沒變、只 commit 一次）、
`test_upsert_同一封帳單第二次_不重插也不再合併`（line_no 已存在 → 不呼叫 `_merge_candidates`）、`test_all_charges_排除merged`（FakeQuery 記下 filter 參數或改用 monkeypatch 驗查詢條件）、
`test_transaction_fields_沒店名用商店類型`。
`tests/test_cardrecon_ui.py`：`test_line_網路消費顯示商店類型`、`test_line_summary`（None／正常／被登出三種）、`test_notify_weekly_沒有清單頁也發LINE摘要`（monkeypatch `post_sync` 記下呼叫）。
`tests/test_cardrecon_ingest.py`：`test_run_weekly_填LINE統計`（走 `_wire`；monkeypatch `repo.weekly_line_stats` 與 `lineinbox.repo.listener_state`）。

- [ ] **Step 2: 跑測試確認失敗** — `scripts/check_tests.sh`
- [ ] **Step 3: 實作**
- [ ] **Step 4: 全綠** — `scripts/check_tests.sh`
- [ ] **Step 5: commit**

---

### Task 3: 處理流程＋listener＋money-line 容器

**Files:**
- Create: `lineinbox/process.py`、`lineinbox/client.py`、`lineinbox/listener.py`、`docker/line.Dockerfile`、`docker/verify_okline.py`
- Modify: `docker-compose.yml`（新 service `line`）
- Test: `tests/test_lineinbox_process.py`、`tests/test_lineinbox_listener.py`

**Interfaces:**
- Consumes: Task 0（`lineinbox.repo`、types、config）、Task 1（`flex.*`、`parse.parse_ctbc_line`、`parse.foreign_amount`）、`cardrecon.repo.upsert_charges`。
- Produces:
  - `process.classify(msg: dict, source: str) -> tuple[InboxMessage, str, Charge | None]`（純函式，不碰 DB）：`message_parts` → `kind`；
    非消費 → `OTHER`；`foreign_amount` → `NON_TWD`；`parse_ctbc_line` 成功 → `PARSED` 與 Charge；否則 `NEEDS_CODEX`。
    `message_id = str(msg["id"])`；`sent_at` ＝ `createdTime`（毫秒）換成台北時間 naive。`PARSERS = {"ctbc": parse_ctbc_line}`。
  - `process.handle(db, msg: dict, source: str) -> str | None`：`lineinbox.repo.exists` 為 True → 回 None、什麼都不寫；
    否則 `classify`；`PARSED` 先 `cardrecon.repo.upsert_charges(db, CHARGE_ID_PREFIX + message_id, [charge])` 再 `save_message`；其他狀態只 `save_message`。回狀態。
  - `client`（OkLine 介面，`okline` 只在函式內 import；**只有讀取**）：`load(path) -> api`（`OkLine.from_tokens_file(path, auto_refresh_schedule=True)`）、
    `find_mid(api, display_name) -> str`（聯絡人 displayName **完全相等**；0 個或多個 → `LookupError`）、`recent(api, mid, count) -> list[dict]`、
    `messages(api) -> Iterator[dict]`（`api.ops.iter_operations(reconnect=False, keepalive=True)` 裡 `type == 26` 且有 `message` 的 `op.message`）、
    `probe(api) -> None`（`api.get_profile()`）、`is_auth_error(exc) -> bool`（`okline.exceptions.LineAuthError`）。
  - `listener.next_delay(failures: int) -> float`：`min(BACKOFF_START * 2 ** failures, BACKOFF_MAX)`。
  - `listener.main(argv: list[str] | None = None) -> int`：
    1. 建 `line_messages`／`line_listener_state` 表（`Base.metadata.create_all(engine, tables=[...])`），`set_state(STARTING)`。
    2. 載入 session、對 `WATCHED` 每個名字 `find_mid`；找不到 → `set_state(ERROR, "找不到聊天室")`，等 `KICKED_POLL_SEC` 再試（不結束程序）。
    3. 補讀：`recent(api, mid, RECENT_COUNT)` 由舊到新、只取 `from == mid` 的，逐則 `handle`；**不往回翻頁**。
    4. `set_state(OK)`；背景 daemon thread 每 `HEARTBEAT_SEC` 在狀態是 OK 時 `set_state(OK)`；`messages(api)` 逐則：`from` 是被監看 mid 才 `handle`，其他直接丟。
    5. 串流丟例外：`is_auth_error(e)`，或 `probe` 丟出 auth error → `set_state(KICKED, ...)`，之後每 `KICKED_POLL_SEC` 看 session 檔 mtime，變了就回到 2
       （**不重試登入、不結束程序**）；其他例外 → `set_state(ERROR, 例外類別名)`、等 `next_delay(failures)` 秒、回到 3（重連前先補讀）。成功收到一則就把 failures 歸零。
    6. `--dry-run`：只做 2、3 的讀取與 `classify`，不寫 DB，印各 `kind`／狀態的筆數（**不印任何訊息文字**），回 0。
    7. 任何 log 都不含訊息文字；錯誤只記例外類別名與簡短說明。
  - `docker/line.Dockerfile`：`FROM money-bot`；`ARG OKLINE_COMMIT=2e3437977368802edcc2219798b9d5333665ebca`；
    `pip install --no-cache-dir --no-deps "okline @ https://github.com/NiceDayZc/OkLine/archive/${OKLINE_COMMIT}.tar.gz"`；
    `pip install --no-cache-dir --no-deps qrcode==8.2`（清華鏡像，同主 Dockerfile 的參數）；`COPY verify_okline.py` 後執行它；
    `ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp PYTHONUNBUFFERED=1`；`CMD ["python", "-m", "lineinbox.listener"]`。
  - `docker/verify_okline.py`：算已安裝 `okline/ltsm/ltsm.wasm` 與 `okline/ltsm/ltsmSandbox.js` 的 sha256，跟
    `58bb4e189ab9bbd7d72ed415258da36afd50e306cb019bab75329d4f5f1b65b3`、`5c66cba945cc039d817e87fef2aa1e28c8adb7be0f94fca5b95bb6bcf5a07c94` 比，不符就 exit 1。
  - `docker-compose.yml` 新 service `line`：`image: money-line`、`build: {context: ./docker, dockerfile: line.Dockerfile}`、`container_name: money-line`、
    `restart: unless-stopped`、`user: "${HOST_UID:-1000}:${HOST_GID:-1000}"`、`depends_on: [db]`、
    `volumes: [".:/app:ro", "${HOME}/.config/money-bot/line:/data"]`、`working_dir: /app`、`secrets: [database_url]`；**沒有** `~/.codex`、沒有其他 secrets、沒有 `environment:` 機密。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_lineinbox_process.py（fixture＋FakeSession＋monkeypatch lineinbox.repo / cardrecon.repo）
def test_實體店_寫刷卡再存訊息():
    status = handle(db, _msg("store"), "ctbc")
    assert status == "parsed"
    assert upserts == [("line:900000000000000001", 1280)]
    assert saved == [("900000000000000001", "parsed")]
def test_入帳通知_只存訊息不寫刷卡(): ...      # deposit → "other"、upserts == []
def test_外幣_只存訊息(): ...                  # foreign_usd → "non_twd"
def test_版型壞掉_等codex(): ...               # store 的 FLEX_JSON 拿掉金額段 → "needs_codex"、upserts == []
def test_已處理過_什麼都不做(): ...             # exists 回 True → None、upserts == saved == []
def test_刷卡寫入失敗_不存訊息(): ...           # upsert 丟例外 → 例外往外拋、saved == []（下次補讀會重做）
```
`tests/test_lineinbox_listener.py`：`test_next_delay`（0→5、1→10、7→600、50→600）、
`test_client_只有讀取`（讀 `lineinbox/client.py` 原始碼，斷言不含 `send_`、`mark_read`、`react`、`unsend`、`add_friend`、`logout`、`set_`、`broadcast`、`.reply(`）、
`test_listener_不印訊息文字`（`--dry-run` 走 monkeypatch 過的 client，fixture 文字不出現在 capsys 輸出、數字有出現）。

- [ ] **Step 2: 跑測試確認失敗** — `scripts/check_tests.sh`
- [ ] **Step 3: 實作**；`docker compose config` 驗 compose 檔語法
- [ ] **Step 4: 全綠** — `scripts/check_tests.sh`
- [ ] **Step 5: commit**

---

### Task 4: watchdog＋Discord 告警＋排程

**Files:**
- Create: `lineinbox/health.py`、`lineinbox/watchdog.py`、`discordbot/lineinbox_ui.py`
- Modify: `main.py`（排程）
- Test: `tests/test_lineinbox_health.py`、`tests/test_lineinbox_watchdog.py`、`tests/test_lineinbox_ui.py`

**Interfaces:**
- Consumes: Task 0（`lineinbox.repo`、types、config）、Task 1（`fallback.*`）、`cardrecon.repo.upsert_charges`、`codex_cli.codex_text`、`discordbot.bridge.post_sync`。
- Produces:
  - `health.alert_kind(state: ListenerState | None, now: datetime, stale_min: int) -> str | None`：None → None；`state == "kicked"` → `"kicked"`；
    `heartbeat_at` 是 None 或 `now - heartbeat_at > stale_min 分鐘` → `"stale"`；否則 None。
  - `health.should_send(kind: str | None, alerted: str | None) -> bool`：`kind is not None and kind != alerted`。
  - `watchdog.run(now: datetime | None = None, db=None) -> dict`：
    1. `pending_codex(db, FALLBACK_PER_RUN)` 逐則：`codex_text(build_prompt(texts), model=CODEX_FALLBACK_MODEL, schema=SCHEMA)`（例外視同失敗）→ `charge_from_reply`；
       成功 → `upsert_charges(db, CHARGE_ID_PREFIX + id, [charge])` 後 `set_status(CODEX_PARSED)`；失敗 → `set_status(UNREADABLE, 原因)` 並收集起來。
    2. 有看不懂的 → `lineinbox_ui.notify_unreadable(items)`。
    3. `alert_kind` + `should_send` 成立 → `lineinbox_ui.notify_listener(kind, state)` 再 `mark_alerted(kind)`。
    4. 回 `{"codex": 成功數, "unreadable": 失敗數, "alert": kind 或 None}`。
  - `lineinbox_ui._chan()` 讀 `DISCORD_INVOICE_CHANNEL_ID`；`notify_unreadable(items: list[InboxMessage]) -> None`：每則一段，時間＋前 12 段文字（截 1000 字），
    文字先 `discord.utils.escape_markdown` 再 `escape_mentions`（外來文字不能變成連結或 tag 人）；
    `notify_listener(kind: str, state: ListenerState) -> None`：`kicked` 寫「LINE 被登出了」、`stale` 寫「超過 1 小時沒有心跳」＋`last_error`；
    兩種都附重新登入步驟（在 `~/Desktop/linebot` 跑 `docker compose run --rm line okline login --save /data/tokens.json --wait 240`，手機掃 QR、確認 PIN；
    listener 會自己發現新的登入接著收，不用重啟）。
  - `main.py`：`_line_watchdog()` 包 try/except（印 `⚠️`，不往外丟）；`scheduler.add_job(_line_watchdog, "interval", minutes=30, id="line_watchdog")`。

- [ ] **Step 1: 寫失敗測試**：`health` 四種情況＋`should_send`（同種不重發、換種要發、None 不發）；
  `watchdog`（autouse 炸彈守衛 `codex_cli._codex_exec`；monkeypatch `codex_cli.codex_text` 回合成 JSON）：成功寫刷卡＋`codex_parsed`、壞回覆 → `unreadable`＋通知一次、
  `kicked` 第一次發、第二次（`alerted == "kicked"`）不發；`lineinbox_ui`：`notify_unreadable` 把 `[x](http://evil)` 與 `@everyone` 跳脫掉（monkeypatch `post_sync` 收 embed）。
- [ ] **Step 2: 跑測試確認失敗** — `scripts/check_tests.sh`
- [ ] **Step 3: 實作**
- [ ] **Step 4: 全綠** — `scripts/check_tests.sh`
- [ ] **Step 5: commit**

---

### Task 5: 收尾（主線）

- [ ] Step 1: 整體凝聚審查：同一筆刷卡只有一列會被列出／配對；其他聊天室內容不落地、不進 log；session 檔只在 money-line；`client.py` 沒有寫入；註解沒有討論語。
- [ ] Step 2: 更新 `README.md`（功能＋重新登入指令）、`CODEBASE.md`（`lineinbox/` 檔案地圖、`line_messages`／`line_listener_state`、`card_charges` 新欄與 `merged`、
  `money-line` service、`line_watchdog` 排程）。`AGENTS.md` 有別人的未 commit 變更，這輪不動；要加的坑寫進回報交給主線。
- [ ] Step 3: master 上 `docker exec -w /app money-bot python -c "import main"`、`docker exec -w /app money-bot python -m pytest tests/ -q`。
- [ ] Step 4: `docker compose build line`（只 build 新 image，不 up）；`docker run --rm --entrypoint python money-line -c "import okline"`。
- [ ] Step 5: 真資料唯讀試跑：用試做的 session 跑 `--dry-run`（不寫 DB），預期消費通知 18 則：實體店 14＋網路 2 → `parsed` 16、海外 2 → `non_twd` 2。
- [ ] Step 6: 部署（主線跟本人說過再做）：
  1. `docker exec -w /app money-bot python -c "import main" && docker restart money-bot`，等 `Application startup complete`，`docker logs money-bot | grep -E '✅|⚠️'` 看到兩個新欄位。
  2. `mkdir -m 700 -p ~/.config/money-bot/line && mv ~/.config/money-bot/line-spike/tokens.json ~/.config/money-bot/line/`
  3. `docker compose up -d line`，`docker logs money-line` 看補讀完成；DB 查 `card_charges` 的 `ctbc_line` 筆數。
  4. 刪試做資料：`rm -r ~/.config/money-bot/line-spike`、`docker rmi okline-spike`。
- [ ] Step 7: 11 月中下旬那期中信帳單進來後，跟本人一起確認第一次合併合對了，這個項目才算完成。
