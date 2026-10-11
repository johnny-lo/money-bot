# 敏感資料遷移到 Docker secrets 設計

日期：2026-10-11　狀態：用戶 2026-10-11 核可

## 1. 背景與目標

要接 Gmail（應用程式密碼）與信用卡 PDF 解密（身分證字號）之前盤點 `.env`，發現所有機密的唯一存放處
是 repo 根目錄的 `.env`，經 `docker-compose.yml` 的 `environment:` 白名單變成容器環境變數。兩條意外外洩路徑：

1. **repo 整個 live-mount 成 `/app`** → 容器裡任何東西（包括讀不可信連結的 codex）都能 `cat /app/.env`；
   autofix worktree、任何在 repo 目錄工作的工具也都摸得到。
2. **環境變數會被子程序繼承**（codex、Playwright）且 `docker inspect money-bot` 看得到明文。

**目標**：機密搬到 repo 外的檔案，經 compose `secrets:` 掛到容器 `/run/secrets/`，程式經單一入口讀取；
`.env` 只留一般設定。

**成功標準**
- 遷移後 `docker inspect money-bot`、`docker exec money-bot cat /proc/1/environ`、`/app/.env` 都看不到任何一個機密值。
- LINE webhook、Discord bot、發票登入、Gemini、Places API、DB 連線行為與遷移前相同。
- 之後有人對機密名稱寫 `os.getenv` / `os.environ`，測試會失敗。
- 在正式容器裡跑 `pytest` 不會讀到真的機密（測試結果與在 CI 一致）。

**非目標**：更換 DB 密碼（用戶決定不換）、`~/.codex` 掛載方式、讓 codex 讀不到 `/run/secrets`（見 §7）、
Gmail / PDF 解密功能本身（下一個項目）。

## 2. 已定決策

| 決策 | 結論 |
|---|---|
| 機制 | Docker Compose `secrets:`（file 型，非 swarm），容器內 `/run/secrets/<小寫名稱>` |
| 主機存放處 | `${HOME}/.config/money-bot/secrets/`，目錄 700、檔案 600，每個機密一個檔 |
| 搬遷清單 | 見 §3，12 個（口頭誤數成 11，2026-10-11 寫計畫時更正）；用戶 2026-10-11 確認 |
| DB 密碼 | 不換；`DATABASE_URL` 只搬位置 |
| 讀取優先序 | 檔案優先，環境變數退路（CI / 測試用） |

## 3. 搬遷清單

| 名稱 | secrets 檔名 | 必填 | 讀取處 |
|---|---|---|---|
| `LINE_CHANNEL_SECRET` | `line_channel_secret` | 選填 | `line_handler.py` |
| `LINE_CHANNEL_ACCESS_TOKEN` | `line_channel_access_token` | 選填 | `line_handler.py` |
| `DISCORD_BOT_TOKEN` | `discord_bot_token` | 選填 | `main.py` |
| `GEMINI_API_KEY` | `gemini_api_key` | 必填 | `gemini.py` ×2 |
| `GOOGLE_PLACES_SERVER_KEY` | `google_places_server_key` | 選填 | `food/places.py` ×3 |
| `DATABASE_URL` | `database_url` | 必填 | `database.py` |
| `EINVOICE_PHONE_1` / `_2` | `einvoice_phone_1` / `_2` | 1 必填、2 選填 | `einvoice.py`、`autofix/verify.py` |
| `EINVOICE_PASSWORD_1` / `_2` | `einvoice_password_1` / `_2` | 同上 | 同上 |
| `GMAIL_APP_PASSWORD` | `gmail_app_password` | 選填 | （尚無，下一項目使用） |
| `NATIONAL_ID` | `national_id` | 選填 | （尚無，下一項目使用） |

留在 `.env`：頻道 ID、`BASE_URL`、`MONTHLY_*`、`BUCKET_RATIOS`、模型名稱、`CODEX_MODEL`、`AUTOFIX_*`、
`GMAIL_ADDRESS`、`GOOGLE_MAPS_BROWSER_KEY`（本來就送到瀏覽器）、`GOOGLE_MAPS_MAP_ID`、`POSTGRES_*`。

## 4. 元件

### 4.1 `app_secrets.py`（新檔，repo 根）

```
get_secret(name: str) -> str | None
```
- 讀 `<SECRETS_DIR>/<name.lower()>`；`SECRETS_DIR` 取自環境變數，預設 `/run/secrets`。
- 檔案存在 → 去頭尾空白；空字串回 `None`（選填項目用空檔佔位，見 §5）。
- 檔案不存在 → 退回 `os.getenv(name)`，空字串同樣回 `None`。
- 不快取（每次讀檔；呼叫點本來就只在 import 期或低頻路徑）。
- 純函式 + 檔案 I/O，不 import 專案其他模組（避免 import 期循環 / 崩潰）。
- **命名**：不能叫 `secrets.py`——會遮蔽標準庫 `secrets`，而 `auth.py`、discord.py、starlette、yt-dlp 都 `import secrets`（2026-10-11 查證），遮蔽後 import 期就崩、webhook 與 bot 全掛。

### 4.2 呼叫點改寫

§3 表中「讀取處」的每個 `os.getenv` / `os.environ[...]` 改成 `get_secret(...)`。
`einvoice.py` 的 `EINVOICE_PHONE_{i}` 迴圈照舊遞增，`get_secret` 對不存在的 i 回 `None`，行為不變。
`autofix/verify.py` 原本 `os.environ[...]`（缺值拋 KeyError）改成 `get_secret` 後缺值要明確拋錯，保留原本「缺就失敗」語意。

### 4.3 `docker-compose.yml`

- 頂層新增 `secrets:`，12 個，`file: ${HOME}/.config/money-bot/secrets/<檔名>`。
- `app` 服務加 `secrets: [...]` 全部 12 個；刪除 `environment:` 裡對應的 10 行（`GMAIL_APP_PASSWORD` 與 `NATIONAL_ID` 本來就不在白名單）。
- compose 要求 file 型 secret 的檔案存在，否則整個 stack 起不來 → 選填項目用**空檔**佔位。

### 4.4 `autofix/bin/probe`

目前用 `--env-file <(grep ... "$REPO/.env")` 把單一載具帳密帶進一次性容器。改成從
`~/.config/money-bot/secrets/einvoice_{phone,password}_N` 讀出、組成同樣兩行 env-file。
仍只帶該載具一組帳密，邊界不變（這個一次性容器不接 compose，沒有 `/run/secrets`，靠 env 退路）。

### 4.5 `scripts/migrate_secrets.sh`（新檔，主機端執行）

1. 建 `~/.config/money-bot/secrets/`（700），備份 `.env` 到 `~/.config/money-bot/env.bak.<時間>`（600）。
2. 對 §3 每個名稱：`.env` 有值 → 寫進檔案（600，無結尾換行）；沒有 → 建空檔。
3. 把 `.env` 中這 12 行改成 `# NAME → ~/.config/money-bot/secrets/<檔名>`。
4. 冪等：已搬過（檔案非空且 `.env` 無該值）就跳過；從不印出任何值。
5. 用 bash 寫，不依賴主機 python（主機沒有 python；`autofix/bin/probe` 的 python3 是例外，不新增依賴）。

## 5. 測試

純單元測試，不連 DB、不出網：

- `tests/test_secrets.py`：`get_secret` 讀檔、去空白、空檔回 None、檔案不存在退環境變數、
  檔案優先於環境變數、`SECRETS_DIR` 覆寫生效。用 `tmp_path` + monkeypatch。
- `tests/test_secrets_guard.py`：掃 repo 內所有 `.py`（排除 `tests/`、`app_secrets.py` 本身），
  §3 任一名稱出現在 `os.getenv(` / `os.environ` 呼叫中就失敗；訊息指出檔案與行號。
- `tests/conftest.py`：autouse fixture 把 `SECRETS_DIR` 指到空的 `tmp_path`。
  理由：在正式容器裡跑 pytest 時 `/run/secrets` 存在，檔案優先會讓 `monkeypatch.delenv` 的「未設定」測試
  （`test_line_optional.py`、`test_places_errors.py`）讀到真值而失敗；也避免測試意外用真金鑰出網。
- 既有測試全數維持通過，不改其斷言。

## 6. 上線步驟（實作者完成程式後，由指揮者與用戶在主機執行）

1. 全套測試 + import 預檢（AGENTS.md §9）。
2. `bash scripts/migrate_secrets.sh`。
3. `docker compose up -d`（改了 compose 的服務定義 → 會 Recreated；看到 `Running` 是警訊）。
4. 輪詢 log 等 `Application startup complete`。
5. 驗證：
   - `docker exec money-bot ls /run/secrets` 有 12 個檔；
   - `docker inspect money-bot --format '{{.Config.Env}}'`、`docker exec money-bot cat /proc/1/environ` 不含任何機密值；
   - LINE：webhook 端點 curl 回非 5xx；Discord：bot 上線；發票：`docker exec` 呼叫一次 `sync_invoices` 或等排程；
     Gemini / Places：各打一次。
6. 全部通過 → 刪除 `env.bak.*`（用戶確認後）。任一失敗 → 把 `env.bak` 蓋回 `.env`、`git revert` 程式變更、`docker compose up -d`。

## 7. 改完後仍存在的風險（寫進 AGENTS.md）

- **codex 讀得到 `/run/secrets`**：唯讀沙箱只擋寫、不擋讀。這次堵掉的是「env 被子程序繼承」與「repo 目錄裡的 .env」；
  要徹底隔離需讓 codex 用另一個 UID 跑，另開項目。
- 主機或容器 root 被拿下時 secrets 照樣可讀——這是減少意外外洩路徑，不是保險箱。
- `NATIONAL_ID` 無法像密碼一樣更換；只掛給需要的服務，且任何 log / Discord 訊息不得含其值（下一項目的約束）。

## 8. 文件更新

- `README.md`、`CODEBASE.md`：環境變數清單拆成「.env 設定」與「secrets」兩欄；新增 `app_secrets.py`、`scripts/migrate_secrets.sh`。
- `.env.example`：機密那幾行改成指向 secrets 的註解。
- `AGENTS.md`：新坑「新增機密是三個地方的事：secrets 檔 + compose `secrets:` 兩處 + `get_secret` 呼叫」，
  以及 §7 的殘餘風險；更新既有「compose 是白名單」那條，註明機密改走 secrets。
- `CLAUDE.md`：「驗 API」段落之外如提到 `.env` 放機密的地方一併修正。
