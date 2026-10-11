# 敏感資料遷移到 Docker secrets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 本專案的執行方式：每個 Task 由指揮者經 Thoth（`thoth dispatch`）派給 worker，在 Thoth worktree 裡實作。

**Goal:** 12 個機密從 `.env`／容器環境變數搬到 repo 外的檔案，經 compose `secrets:` 掛進 `/run/secrets/`，程式只經 `app_secrets.get_secret()` 讀取。

**Architecture:** 新增無相依的 `app_secrets.py`（檔案優先、環境變數退路）；所有讀機密的呼叫點改用它，並以 guard 測試鎖死；compose 改掛 secrets、刪除對應 `environment:` 行；主機端 `scripts/migrate_secrets.sh` 把 `.env` 的值搬成檔案。上線（實際搬遷與重啟）不在任何 Task 內，由指揮者與用戶在主機執行（spec §6）。

**Tech Stack:** Python 3.11（容器內）、pytest、bash、Docker Compose v2 file-based secrets。

**Spec:** `docs/superpowers/specs/2026-10-11-docker-secrets-design.md`

## Global Constraints

- 讀取入口檔名是 `app_secrets.py`（repo 根），函式 `get_secret(name: str) -> str | None`；**不可**命名為 `secrets.py`（會遮蔽標準庫，`auth.py`、discord、starlette、yt-dlp 都 `import secrets`）。
- secrets 檔名 = 機密名稱全小寫；容器內目錄預設 `/run/secrets`，可由環境變數 `SECRETS_DIR` 覆寫。
- 主機存放處：`${HOME}/.config/money-bot/secrets/`，目錄 700、檔案 600。
- 12 個機密（順序固定，各處清單照抄）：`LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `DISCORD_BOT_TOKEN`, `GEMINI_API_KEY`, `GOOGLE_PLACES_SERVER_KEY`, `DATABASE_URL`, `EINVOICE_PHONE_1`, `EINVOICE_PASSWORD_1`, `EINVOICE_PHONE_2`, `EINVOICE_PASSWORD_2`, `GMAIL_APP_PASSWORD`, `NATIONAL_ID`。
- 檔案存在 → 去頭尾空白後回傳，空字串回 `None`（**不**退回環境變數）；檔案不存在 → `os.getenv(name)`，空字串回 `None`。
- 任何程式、腳本、log、測試輸出都不得印出機密值。
- 測試：純單元測試，不連 DB、不出網。執行一律 `scripts/check_tests.sh`（在 worktree 根目錄跑；它用一次性容器掛 worktree）。**不要**用 `docker exec money-bot ...`——那跑的是主目錄不是你的 worktree。
- **禁止**：讀取或修改主機的 `/home/johnny/Desktop/linebot/.env`、`~/.config/money-bot/`；執行 `docker compose up` / `docker restart` / `scripts/migrate_secrets.sh`（測試裡對 tmp 目錄跑除外）；碰正式容器 `money-bot`、`money-db`。
- 文件：commit 前更新 `CODEBASE.md`（每個 Task）；Task 3 另更新 `README.md`、`AGENTS.md`、`.env.example`。文件用繁體中文。
- commit 訊息繁體中文，結尾加 `Co-Authored-By` 行（照 repo 慣例）。

## Review Focus

1. **在正式容器裡跑 pytest**（`/run/secrets` 有真值）：測試必須讀不到真金鑰——`tests/conftest.py` 的 autouse fixture 把 `SECRETS_DIR` 指到空目錄（Task 1 的 `test_conftest_isolates_real_secrets` 釘住）。注意 import 期讀取（`database.py`）發生在 fixture 之前，行為與今天相同（今天 env 也有真值），不在此修。
2. **選填機密的空佔位檔**（第二組載具、LINE 未設）：空檔必須等同未設定，`einvoice._list_carriers()` 不能冒出空帳密的載具（Task 2 `test_list_carriers_reads_secret_files` 釘住）。
3. **`.env` 值的寫法**：密碼含 `#`、含空白、加了引號、行尾註解、CRLF——搬遷後檔案內容必須是真正的值（Task 3 `test_value_parsing_*` 釘住）。
4. **重跑搬遷腳本**：第二次跑不得把已搬的檔案清空或覆寫成註解文字；secrets 檔與 `.env` 值不同時不得覆寫檔案（Task 3 `test_rerun_is_idempotent`、`test_conflict_keeps_file_and_env_line`）。
5. **之後有人加新功能又寫 `os.getenv("GEMINI_API_KEY")`**：guard 測試要抓到，包括 f-string 的 `EINVOICE_PHONE_{i}`（Task 2 `test_guard_detects_patterns` 釘住）。

---

### Task 1: `app_secrets.get_secret` 與測試隔離

**Files:**
- Create: `app_secrets.py`
- Create: `tests/test_secrets.py`
- Modify: `tests/conftest.py`（新增 autouse fixture）
- Modify: `CODEBASE.md`（檔案地圖加 `app_secrets.py` 一行）

**Interfaces:**
- Produces: `app_secrets.get_secret(name: str) -> str | None`；模組常數 `app_secrets.DEFAULT_SECRETS_DIR = "/run/secrets"`。

- [ ] **Step 1: 寫失敗測試** `tests/test_secrets.py`

```python
"""app_secrets.get_secret：檔案優先、環境變數退路、空值一律 None。"""
import os

import app_secrets
from app_secrets import get_secret


def _secrets(tmp_path, monkeypatch, files: dict[str, str]):
    d = tmp_path / "secrets"
    d.mkdir()
    for name, value in files.items():
        (d / name).write_text(value, encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(d))
    return d


def test_reads_lowercase_file(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"gemini_api_key": "abc"})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert get_secret("GEMINI_API_KEY") == "abc"


def test_strips_newline_and_crlf(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"gemini_api_key": "abc\r\n"})
    assert get_secret("GEMINI_API_KEY") == "abc"


def test_keeps_inner_spaces_and_hash(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"einvoice_password_1": "p@ss #1 x\n"})
    assert get_secret("EINVOICE_PASSWORD_1") == "p@ss #1 x"


def test_empty_file_is_none_even_if_env_set(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"einvoice_phone_2": ""})
    monkeypatch.setenv("EINVOICE_PHONE_2", "from-env")
    assert get_secret("EINVOICE_PHONE_2") is None


def test_whitespace_only_file_is_none(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"national_id": "  \n"})
    assert get_secret("NATIONAL_ID") is None


def test_file_wins_over_env(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"discord_bot_token": "from-file"})
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "from-env")
    assert get_secret("DISCORD_BOT_TOKEN") == "from-file"


def test_missing_file_falls_back_to_env(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {})
    monkeypatch.setenv("DISCORD_BOT_TOKEN", " from-env ")
    assert get_secret("DISCORD_BOT_TOKEN") == "from-env"


def test_missing_everywhere_is_none(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {})
    monkeypatch.delenv("EINVOICE_PHONE_3", raising=False)
    assert get_secret("EINVOICE_PHONE_3") is None


def test_empty_env_is_none(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {})
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "")
    assert get_secret("LINE_CHANNEL_SECRET") is None


def test_missing_secrets_dir_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert get_secret("GEMINI_API_KEY") == "from-env"


def test_default_dir_is_run_secrets():
    assert app_secrets.DEFAULT_SECRETS_DIR == "/run/secrets"


def test_conftest_isolates_real_secrets():
    """conftest 的 autouse fixture：測試期間 SECRETS_DIR 指向空目錄，讀不到正式容器的 /run/secrets。"""
    d = os.environ["SECRETS_DIR"]
    assert d != "/run/secrets"
    assert os.path.isdir(d) and os.listdir(d) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `scripts/check_tests.sh`
Expected: `tests/test_secrets.py` 收集失敗 `ModuleNotFoundError: No module named 'app_secrets'`。

- [ ] **Step 3: 實作** `app_secrets.py`

```python
"""機密讀取的唯一入口（不可改名成 secrets.py：會遮蔽標準庫 secrets，auth.py / discord / starlette 都在用）。

正式環境：docker-compose.yml 的 secrets: 把主機 ~/.config/money-bot/secrets/<小寫名稱> 掛到
/run/secrets/<小寫名稱>。機密不放 .env、不進容器環境變數——環境變數會被 codex / Playwright 子程序繼承，
`docker inspect` 也看得到明文；.env 又在 live-mount 的 /app 底下，容器裡誰都 cat 得到。

讀取規則：
- 檔案存在 → 去頭尾空白；空檔＝未設定（選填機密用空檔佔位，因為 compose 要求檔案存在），不退回環境變數。
- 檔案不存在 → 退回環境變數（CI、測試、autofix 一次性 probe 容器沒有 /run/secrets）。
不 import 專案其他模組：database.py / line_handler.py 在 import 期就呼叫它，這裡崩 = 全站掛。
"""
import os
from pathlib import Path

DEFAULT_SECRETS_DIR = "/run/secrets"


def get_secret(name: str) -> str | None:
    path = Path(os.getenv("SECRETS_DIR", DEFAULT_SECRETS_DIR)) / name.lower()
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
    else:
        value = (os.getenv(name) or "").strip()
    return value or None
```

- [ ] **Step 4: conftest 加 autouse fixture**（加在既有 `_autofix_off` 之後，不動它）

```python
@pytest.fixture(autouse=True)
def _no_real_secrets(monkeypatch, tmp_path_factory):
    """測試一律讀不到正式容器的 /run/secrets。

    標準測試指令在正式容器裡跑，/run/secrets 有真值；get_secret 檔案優先，
    不隔離的話 monkeypatch.delenv 的「未設定」測試會讀到真金鑰而失敗，甚至拿真金鑰出網。
    要測讀檔的測試自己 setenv SECRETS_DIR 到自己的 tmp 目錄。
    """
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path_factory.mktemp("no-secrets")))
```

- [ ] **Step 5: 跑測試確認通過**

Run: `scripts/check_tests.sh`
Expected: `IMPORT_OK`，全部 passed（基準 654 + 本 Task 新增 12 = 666 passed），0 failed。

- [ ] **Step 6: 更新 `CODEBASE.md`** 檔案地圖（根目錄檔案區，照既有格式）加一行：
`├── app_secrets.py       # 機密讀取唯一入口 get_secret(name)：讀 /run/secrets/<小寫名>（SECRETS_DIR 可覆寫）→ 不存在退環境變數；空值回 None。不可改名 secrets.py（遮蔽標準庫）。測 tests/test_secrets.py`

- [ ] **Step 7: Commit**

```bash
git add app_secrets.py tests/test_secrets.py tests/conftest.py CODEBASE.md
git commit -m "feat(secrets): 新增 app_secrets.get_secret——機密檔優先、環境變數退路；測試期間隔離 /run/secrets"
```

---

### Task 2: 所有呼叫點改用 `get_secret` ＋ guard 測試

**Files:**
- Modify: `database.py:10`、`line_handler.py:13-14`、`gemini.py:31,49`、`food/places.py:138,201,286`、`main.py:250`、`einvoice.py:619-627`（`_list_carriers`）、`autofix/verify.py:30-34`（`_scrape`）
- Create: `tests/test_secrets_guard.py`
- Create: `tests/test_secrets_callsites.py`
- Modify: `CODEBASE.md`（環境變數段落註明機密改經 `get_secret`）

**Interfaces:**
- Consumes: `app_secrets.get_secret(name: str) -> str | None`（Task 1）。
- Produces: `tests/test_secrets_guard.py` 內的 `find_violations(root: pathlib.Path) -> list[str]`（只供測試用）。

- [ ] **Step 1: 寫 guard 測試** `tests/test_secrets_guard.py`

```python
"""機密只能經 app_secrets.get_secret 讀：程式碼裡對機密名稱寫 os.getenv / os.environ 就失敗。"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET_NAMES = [
    "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "DISCORD_BOT_TOKEN", "GEMINI_API_KEY",
    "GOOGLE_PLACES_SERVER_KEY", "DATABASE_URL", "EINVOICE_PHONE_", "EINVOICE_PASSWORD_",
    "GMAIL_APP_PASSWORD", "NATIONAL_ID",
]
# 豁免：一次性 probe 容器沒有 /run/secrets，autofix/bin/probe 只把單一載具帳密經 env 帶進去
EXEMPT = {"autofix/probes/einvoice_probe.py"}
SKIP_PARTS = {"tests", "frontend", "node_modules", "docs", "data", "__pycache__", "venv"}
ENV_READ = re.compile(r"\bos\.(getenv|environ)\b")


def find_violations(root: pathlib.Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        if rel.as_posix() in EXEMPT or rel.as_posix() == "app_secrets.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if ENV_READ.search(line) and any(n in line for n in SECRET_NAMES):
                out.append(f"{rel.as_posix()}:{i}: {line.strip()}")
    return out


def test_no_direct_env_reads_of_secrets():
    v = find_violations(ROOT)
    assert v == [], "機密要經 app_secrets.get_secret 讀，不能 os.getenv / os.environ：\n" + "\n".join(v)


def test_guard_detects_patterns(tmp_path):
    (tmp_path / "bad.py").write_text(
        'import os\n'
        'a = os.getenv(f"EINVOICE_PHONE_{i}")\n'
        'b = os.environ["GEMINI_API_KEY"]\n'
        'c = os.environ.get("NATIONAL_ID", "")\n',
        encoding="utf-8")
    (tmp_path / "ok.py").write_text(
        'import os\n'
        'from app_secrets import get_secret\n'
        'a = get_secret("GEMINI_API_KEY")\n'
        'b = os.getenv("MODEL_NAME")\n'
        'print("未設定 DISCORD_BOT_TOKEN")\n',
        encoding="utf-8")
    v = find_violations(tmp_path)
    assert [x.split(":")[0:2] for x in v] == [["bad.py", "2"], ["bad.py", "3"], ["bad.py", "4"]]


def test_guard_skips_tests_and_hidden_dirs(tmp_path):
    for d in ("tests", ".claude/worktrees/x"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "t.py").write_text('import os\nos.getenv("GEMINI_API_KEY")\n', encoding="utf-8")
    assert find_violations(tmp_path) == []
```

- [ ] **Step 2: 寫呼叫點行為測試** `tests/test_secrets_callsites.py`

```python
"""呼叫點真的從 secrets 檔讀（不是只換了名字）。全部不出網：網路呼叫一律 monkeypatch。"""
import asyncio
import importlib
import json

import pytest


def _secrets(tmp_path, monkeypatch, files: dict[str, str]):
    d = tmp_path / "secrets"
    d.mkdir()
    for name, value in files.items():
        (d / name).write_text(value, encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(d))


def test_list_carriers_reads_secret_files(tmp_path, monkeypatch):
    import einvoice
    for k in ("EINVOICE_PHONE_1", "EINVOICE_PASSWORD_1", "EINVOICE_PHONE_2", "EINVOICE_PASSWORD_2"):
        monkeypatch.delenv(k, raising=False)
    _secrets(tmp_path, monkeypatch, {
        "einvoice_phone_1": "0911000001\n", "einvoice_password_1": "pw1",
        "einvoice_phone_2": "", "einvoice_password_2": "",   # 選填：空佔位
    })
    assert einvoice._list_carriers() == [(1, "0911000001", "pw1")]


def test_line_enabled_from_secret_files(tmp_path, monkeypatch):
    import line_handler
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    _secrets(tmp_path, monkeypatch, {"line_channel_access_token": "tok", "line_channel_secret": "sec"})
    try:
        assert importlib.reload(line_handler).LINE_ENABLED is True
    finally:
        # 重載回「沒有機密」的測試環境，別讓 tok/sec 留在模組狀態污染其他測試
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("SECRETS_DIR", str(empty))
        importlib.reload(line_handler)


def test_gemini_text_uses_key_from_file(tmp_path, monkeypatch):
    import gemini
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _secrets(tmp_path, monkeypatch, {"gemini_api_key": "FILEKEY"})
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}).encode()

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(gemini.urllib.request, "urlopen", fake_urlopen)
    assert gemini.gemini_text("hi", model="m") == "ok"
    assert "key=FILEKEY" in seen["url"]


def test_places_search_uses_key_from_file(tmp_path, monkeypatch):
    from food import places
    monkeypatch.delenv("GOOGLE_PLACES_SERVER_KEY", raising=False)
    _secrets(tmp_path, monkeypatch, {"google_places_server_key": "PKEY"})
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"places": []}).encode()

    def fake_urlopen(req, timeout=None):
        seen["key"] = req.get_header("X-goog-api-key")
        return _Resp()

    monkeypatch.setattr(places.urllib.request, "urlopen", fake_urlopen)
    assert places.search_text("鼎泰豐") is None
    assert seen["key"] == "PKEY"


def test_verify_scrape_reads_secret_files(tmp_path, monkeypatch):
    import einvoice
    from autofix import verify
    _secrets(tmp_path, monkeypatch, {"einvoice_phone_1": "0911000001", "einvoice_password_1": "pw1"})
    got = {}

    async def fake_scrape(phone, pw, days):
        got["args"] = (phone, pw, days)
        return [object(), object()]

    monkeypatch.setattr(einvoice, "_scrape_carrier", fake_scrape)
    assert verify._scrape(1) == 2
    assert got["args"] == ("0911000001", "pw1", 1)


def test_verify_scrape_missing_secret_raises(tmp_path, monkeypatch):
    from autofix import verify
    monkeypatch.delenv("EINVOICE_PHONE_1", raising=False)
    monkeypatch.delenv("EINVOICE_PASSWORD_1", raising=False)
    _secrets(tmp_path, monkeypatch, {"einvoice_phone_1": "", "einvoice_password_1": ""})
    with pytest.raises(KeyError):
        verify._scrape(1)
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `scripts/check_tests.sh`
Expected: `test_no_direct_env_reads_of_secrets` FAIL（列出 database.py、line_handler.py、gemini.py、food/places.py、main.py、einvoice.py、autofix/verify.py 的行）；`test_secrets_callsites.py` 多數 FAIL。

- [ ] **Step 4: 改呼叫點**（每個檔案在既有 import 區加 `from app_secrets import get_secret`；`autofix/verify.py` 在函式內 import，照它既有的 `import einvoice` 寫法）

- `database.py`：`DATABASE_URL = os.getenv("DATABASE_URL")` → `DATABASE_URL = get_secret("DATABASE_URL")`（`load_dotenv()` 保留：`.env` 仍提供一般設定）。
- `line_handler.py:13-14`：`os.getenv("LINE_CHANNEL_ACCESS_TOKEN")` → `get_secret("LINE_CHANNEL_ACCESS_TOKEN")`；`LINE_CHANNEL_SECRET` 同。上方註解裡的舊寫法說明保留。
- `gemini.py:31,49`：`api_key = os.getenv("GEMINI_API_KEY")` → `api_key = get_secret("GEMINI_API_KEY")`。
- `food/places.py:138,201,286`：`key = os.getenv("GOOGLE_PLACES_SERVER_KEY")` → `key = get_secret("GOOGLE_PLACES_SERVER_KEY")`。
- `main.py:250`：`discord_token = os.getenv("DISCORD_BOT_TOKEN")` → `discord_token = get_secret("DISCORD_BOT_TOKEN")`。
- `einvoice.py` `_list_carriers`：

```python
def _list_carriers() -> list[tuple[int, str, str]]:
    """從 secrets 蒐集所有載具（空佔位檔＝未設定）。回傳 [(編號, 手機, 密碼), ...]"""
    carriers = []
    for i in range(1, 10):
        phone = get_secret(f"EINVOICE_PHONE_{i}")
        password = get_secret(f"EINVOICE_PASSWORD_{i}")
        if phone and password:
            carriers.append((i, phone, password))
    return carriers
```

- `autofix/verify.py` `_scrape`：

```python
def _scrape(label: int) -> int:
    import einvoice
    from app_secrets import get_secret
    phone = get_secret(f"EINVOICE_PHONE_{label}")
    pw = get_secret(f"EINVOICE_PASSWORD_{label}")
    if not (phone and pw):
        # 保留舊的 os.environ[...] 語意：缺帳密就失敗，check() 會接住並回報
        raise KeyError(f"載具{label} 帳密未設定（secrets 檔 einvoice_phone_{label} / einvoice_password_{label}）")
    return len(asyncio.run(einvoice._scrape_carrier(phone, pw, 1)))
```

改完若某檔的 `import os` 已無其他用途，保留不刪（不做無關清理）。

- [ ] **Step 5: 跑測試確認通過**

Run: `scripts/check_tests.sh`
Expected: `IMPORT_OK`，0 failed（Task 1 後的數量 + 本 Task 新增 9）。

- [ ] **Step 6: 更新 `CODEBASE.md`**：環境變數段落（`BASE_URL (對外網址...` 那行附近）前加一句：「12 個機密（清單見 `app_secrets.py` 與 docker-compose.yml `secrets:`）一律經 `app_secrets.get_secret()` 讀，`tests/test_secrets_guard.py` 擋 `os.getenv`。」

- [ ] **Step 7: Commit**

```bash
git add database.py line_handler.py gemini.py food/places.py main.py einvoice.py autofix/verify.py tests/test_secrets_guard.py tests/test_secrets_callsites.py CODEBASE.md
git commit -m "refactor(secrets): 讀機密的呼叫點全改用 get_secret，guard 測試擋 os.getenv 回流"
```

---

### Task 3: compose secrets、搬遷腳本、probe 與文件

**Files:**
- Create: `scripts/migrate_secrets.sh`
- Create: `tests/test_migrate_secrets.py`
- Modify: `docker-compose.yml`（app 服務 `environment:` 刪 10 行、加 `secrets:`；頂層加 `secrets:`）
- Modify: `autofix/bin/probe:34`（einvoice 帳密改從 secrets 檔讀）
- Modify: `.env.example`、`README.md`、`CODEBASE.md`、`AGENTS.md`

**Interfaces:**
- Consumes: 檔名規則（機密名稱小寫）與 12 個機密清單（Global Constraints）。
- Produces: `scripts/migrate_secrets.sh [--env FILE] [--dest DIR]`，預設 `--env <repo>/.env`、`--dest $HOME/.config/money-bot/secrets`；成功 exit 0，參數錯誤或找不到 env 檔 exit 2。

- [ ] **Step 1: 寫失敗測試** `tests/test_migrate_secrets.py`（用 subprocess 跑 bash，全在 tmp_path，不碰真 `.env`）

```python
"""scripts/migrate_secrets.sh：只在 tmp 目錄跑，驗搬遷結果、權限、冪等、從不印出值。"""
import pathlib
import stat
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "migrate_secrets.sh"
NAMES = [
    "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "DISCORD_BOT_TOKEN", "GEMINI_API_KEY",
    "GOOGLE_PLACES_SERVER_KEY", "DATABASE_URL", "EINVOICE_PHONE_1", "EINVOICE_PASSWORD_1",
    "EINVOICE_PHONE_2", "EINVOICE_PASSWORD_2", "GMAIL_APP_PASSWORD", "NATIONAL_ID",
]


def _run(tmp_path, env_text: str):
    env = tmp_path / ".env"
    if not env.exists():
        env.write_text(env_text, encoding="utf-8")
    dest = tmp_path / "cfg" / "secrets"
    r = subprocess.run(["bash", str(SCRIPT), "--env", str(env), "--dest", str(dest)],
                       capture_output=True, text=True)
    return r, env, dest


def test_moves_values_and_creates_all_files(tmp_path):
    r, env, dest = _run(tmp_path, "BASE_URL=https://x\nGEMINI_API_KEY=gk-123\nDATABASE_URL=postgresql://u:p@db/x\n")
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.iterdir()) == sorted(n.lower() for n in NAMES)
    assert (dest / "gemini_api_key").read_text() == "gk-123"
    assert (dest / "database_url").read_text() == "postgresql://u:p@db/x"
    assert (dest / "national_id").read_text() == ""          # 沒值 → 空佔位
    text = env.read_text()
    assert "BASE_URL=https://x" in text                       # 一般設定不動
    assert "gk-123" not in text and "GEMINI_API_KEY=" not in text
    assert "# GEMINI_API_KEY →" in text


def test_permissions(tmp_path):
    r, env, dest = _run(tmp_path, "GEMINI_API_KEY=gk\n")
    assert r.returncode == 0, r.stderr
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    for p in dest.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    baks = list((tmp_path / "cfg").glob("env.bak.*"))
    assert len(baks) == 1 and stat.S_IMODE(baks[0].stat().st_mode) == 0o600
    assert "GEMINI_API_KEY=gk" in baks[0].read_text()          # 備份是搬遷前原樣


def test_never_prints_values(tmp_path):
    r, env, dest = _run(tmp_path, "GEMINI_API_KEY=very-secret-value\nNATIONAL_ID=A123456789\n")
    assert r.returncode == 0, r.stderr
    assert "very-secret-value" not in r.stdout + r.stderr
    assert "A123456789" not in r.stdout + r.stderr


def test_value_parsing_hash_and_spaces(tmp_path):
    r, env, dest = _run(tmp_path, "EINVOICE_PASSWORD_1=ab#cd\nEINVOICE_PASSWORD_2=xy  # 行尾註解\n")
    assert r.returncode == 0, r.stderr
    assert (dest / "einvoice_password_1").read_text() == "ab#cd"   # 前面沒空白的 # 是值的一部分
    assert (dest / "einvoice_password_2").read_text() == "xy"


def test_value_parsing_quotes_and_crlf(tmp_path):
    r, env, dest = _run(tmp_path, 'GEMINI_API_KEY="a b #c"\r\nDISCORD_BOT_TOKEN=\'t#1\'\r\nLINE_CHANNEL_SECRET=s1\r\n')
    assert r.returncode == 0, r.stderr
    assert (dest / "gemini_api_key").read_text() == "a b #c"
    assert (dest / "discord_bot_token").read_text() == "t#1"
    assert (dest / "line_channel_secret").read_text() == "s1"


def test_rerun_is_idempotent(tmp_path):
    r1, env, dest = _run(tmp_path, "GEMINI_API_KEY=gk-123\n")
    r2, env, dest = _run(tmp_path, "")          # 第二次：.env 已被改寫過
    assert r1.returncode == 0 and r2.returncode == 0, r2.stderr
    assert (dest / "gemini_api_key").read_text() == "gk-123"
    assert env.read_text().count("# GEMINI_API_KEY →") == 1


def test_conflict_keeps_file_and_env_line(tmp_path):
    dest = tmp_path / "cfg" / "secrets"
    dest.mkdir(parents=True)
    (dest / "gemini_api_key").write_text("old-value")
    r, env, dest = _run(tmp_path, "GEMINI_API_KEY=new-value\n")
    assert r.returncode == 0, r.stderr
    assert (dest / "gemini_api_key").read_text() == "old-value"
    assert "GEMINI_API_KEY=new-value" in env.read_text()          # 衝突的那行留著讓人工比對
    assert "GEMINI_API_KEY" in r.stderr and "new-value" not in r.stderr


def test_missing_env_file_exits_2(tmp_path):
    r = subprocess.run(["bash", str(SCRIPT), "--env", str(tmp_path / "nope"), "--dest", str(tmp_path / "d")],
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_compose_lists_same_secrets():
    """docker-compose.yml 的 secrets 清單要跟這 12 個一致（不解析 YAML：image 不保證有 pyyaml）。"""
    text = (SCRIPT.parent.parent / "docker-compose.yml").read_text(encoding="utf-8")
    for n in NAMES:
        assert f"/.config/money-bot/secrets/{n.lower()}" in text, n
        assert f"- {n}=" not in text, f"{n} 還在 environment: 白名單裡"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `scripts/check_tests.sh`
Expected: `tests/test_migrate_secrets.py` 多數 FAIL（腳本不存在，bash exit 127；compose 測試找不到 secrets 路徑）。

- [ ] **Step 3: 實作** `scripts/migrate_secrets.sh`（`chmod +x`）

```bash
#!/usr/bin/env bash
# 把 .env 裡的機密搬到 repo 外的 secrets 檔（docker-compose.yml 的 secrets: 掛進 /run/secrets）。
# 冪等、從不印出任何值。先備份 .env 到 secrets 目錄的上一層（env.bak.<時間>，600）。
# 用法：scripts/migrate_secrets.sh [--env FILE] [--dest DIR]
#   預設 --env <repo>/.env  --dest $HOME/.config/money-bot/secrets
# 退出碼：0 完成（含衝突警告）／2 參數或檔案有問題
set -euo pipefail
NAMES=(LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN DISCORD_BOT_TOKEN GEMINI_API_KEY
       GOOGLE_PLACES_SERVER_KEY DATABASE_URL EINVOICE_PHONE_1 EINVOICE_PASSWORD_1
       EINVOICE_PHONE_2 EINVOICE_PASSWORD_2 GMAIL_APP_PASSWORD NATIONAL_ID)
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO/.env"
DEST="$HOME/.config/money-bot/secrets"
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_FILE="${2:?}"; shift 2 ;;
    --dest) DEST="${2:?}"; shift 2 ;;
    *) echo "未知參數：$1" >&2; exit 2 ;;
  esac
done
[ -f "$ENV_FILE" ] || { echo "找不到 env 檔：$ENV_FILE" >&2; exit 2; }

# env_value KEY FILE —— 照 docker compose .env 規則取值（刻意不 source：那會執行檔案內容）。
# 引號內照抄；未加引號時「空白+#」之後是註解，緊貼的 # 是值的一部分（密碼可能含 #）。
env_value() {
  local key="$1" file="$2" line v
  line=$(grep -m1 -E "^[[:space:]]*${key}=" "$file") || return 0
  v=${line#*=}
  v=${v%$'\r'}
  v="${v#"${v%%[![:space:]]*}"}"
  case "$v" in
    \"*) v=${v#\"}; v=${v%%\"*} ;;
    \'*) v=${v#\'}; v=${v%%\'*} ;;
    *) v=$(printf '%s' "$v" | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//') ;;
  esac
  printf '%s' "$v"
}

umask 077
mkdir -p "$DEST"
chmod 700 "$DEST"
bak="$(dirname "$DEST")/env.bak.$(date +%Y%m%d-%H%M%S)"
cp "$ENV_FILE" "$bak"
chmod 600 "$bak"

moved=0; conflicts=0
for n in "${NAMES[@]}"; do
  fname=$(printf '%s' "$n" | tr '[:upper:]' '[:lower:]')
  f="$DEST/$fname"
  v=$(env_value "$n" "$ENV_FILE")
  if [ -n "$v" ]; then
    if [ -s "$f" ] && [ "$(cat "$f")" != "$v" ]; then
      echo "⚠️ $n：secrets 檔已有不同的值——保留檔案、.env 那行也不動，請人工比對" >&2
      conflicts=$((conflicts + 1))
      continue
    fi
    printf '%s' "$v" > "$f"
    moved=$((moved + 1))
    sed -i -E "s|^[[:space:]]*${n}=.*$|# ${n} → ${DEST}/${fname}|" "$ENV_FILE"
  else
    [ -e "$f" ] || : > "$f"
  fi
  chmod 600 "$f"
done
echo "完成：搬入 $moved 個、衝突 $conflicts 個；.env 備份：$bak"
```

- [ ] **Step 4: 改 `docker-compose.yml`**

`app` 服務的 `environment:` 刪除這 10 行：`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`DATABASE_URL`、`GEMINI_API_KEY`、`GOOGLE_PLACES_SERVER_KEY`、`DISCORD_BOT_TOKEN`、`EINVOICE_PHONE_1`、`EINVOICE_PASSWORD_1`、`EINVOICE_PHONE_2`、`EINVOICE_PASSWORD_2`。在 `app` 服務的 `volumes:` 之後加：

```yaml
    # 機密不走 environment:（會被 codex/Playwright 子程序繼承、docker inspect 看得到）。
    # 主機檔在 repo 外：~/.config/money-bot/secrets/（scripts/migrate_secrets.sh 產生）；
    # 程式經 app_secrets.get_secret() 讀 /run/secrets/<小寫名>。選填的沒值也要有空檔，否則 compose 起不來。
    secrets:
      - line_channel_secret
      - line_channel_access_token
      - discord_bot_token
      - gemini_api_key
      - google_places_server_key
      - database_url
      - einvoice_phone_1
      - einvoice_password_1
      - einvoice_phone_2
      - einvoice_password_2
      - gmail_app_password
      - national_id
```

檔案最底（頂層 `volumes:` 之後）加：

```yaml
secrets:
  line_channel_secret:
    file: ${HOME}/.config/money-bot/secrets/line_channel_secret
  line_channel_access_token:
    file: ${HOME}/.config/money-bot/secrets/line_channel_access_token
  discord_bot_token:
    file: ${HOME}/.config/money-bot/secrets/discord_bot_token
  gemini_api_key:
    file: ${HOME}/.config/money-bot/secrets/gemini_api_key
  google_places_server_key:
    file: ${HOME}/.config/money-bot/secrets/google_places_server_key
  database_url:
    file: ${HOME}/.config/money-bot/secrets/database_url
  einvoice_phone_1:
    file: ${HOME}/.config/money-bot/secrets/einvoice_phone_1
  einvoice_password_1:
    file: ${HOME}/.config/money-bot/secrets/einvoice_password_1
  einvoice_phone_2:
    file: ${HOME}/.config/money-bot/secrets/einvoice_phone_2
  einvoice_password_2:
    file: ${HOME}/.config/money-bot/secrets/einvoice_password_2
  gmail_app_password:
    file: ${HOME}/.config/money-bot/secrets/gmail_app_password
  national_id:
    file: ${HOME}/.config/money-bot/secrets/national_id
```

`db` 服務那段「真要換密碼：ALTER USER + 同步改 .env 的 DATABASE_URL」註解改成「…＋同步改 ~/.config/money-bot/secrets/database_url」。

- [ ] **Step 5: 改 `autofix/bin/probe`** einvoice 分支：在 `budget=` 那行之前加 secrets 檔檢查，並把 `--env-file` 那行換掉

```bash
    sdir="$HOME/.config/money-bot/secrets"
    for k in phone password; do
      [ -s "$sdir/einvoice_${k}_$n" ] || { echo "載具$n 的 secrets 檔 einvoice_${k}_$n 不存在或是空的" >&2; exit 2; }
    done
```

```bash
      --env-file <(printf 'EINVOICE_PHONE_%s=%s\nEINVOICE_PASSWORD_%s=%s\n' \
                     "$n" "$(cat "$sdir/einvoice_phone_$n")" "$n" "$(cat "$sdir/einvoice_password_$n")") \
```

（仍只帶該載具一組帳密進一次性容器；`einvoice_probe.py` 不改，靠 env 讀——它在 guard 測試的 EXEMPT 裡。）

- [ ] **Step 6: 跑測試確認通過＋ compose 語法驗證**

Run: `scripts/check_tests.sh`
Expected: `IMPORT_OK`，0 failed。

Run（假 HOME、假 BASE_URL，worktree 沒有 .env；只驗語法與 secrets 解析，不起任何容器）：
```bash
H=$(mktemp -d) && mkdir -p "$H/.config/money-bot/secrets" && for n in line_channel_secret line_channel_access_token discord_bot_token gemini_api_key google_places_server_key database_url einvoice_phone_1 einvoice_password_1 einvoice_phone_2 einvoice_password_2 gmail_app_password national_id; do : > "$H/.config/money-bot/secrets/$n"; done && HOME="$H" BASE_URL=https://x docker compose -f docker-compose.yml config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin); print(len(c["secrets"]), len(c["services"]["app"]["secrets"]))'
```
Expected: `12 12`。

Run: `bash -n autofix/bin/probe && bash -n scripts/migrate_secrets.sh && echo SYNTAX_OK`
Expected: `SYNTAX_OK`。

- [ ] **Step 7: 文件**

- `.env.example`：12 個機密的行改成註解，格式 `# GEMINI_API_KEY → ~/.config/money-bot/secrets/gemini_api_key（scripts/migrate_secrets.sh 從 .env 搬過去）`；檔頭加一段說明機密放 secrets、`.env` 只放一般設定。`POSTGRES_*` 不動。
- `README.md`：環境變數／設定段落改成兩類（`.env` 一般設定 vs. secrets 機密），寫明全新安裝流程：`cp .env.example .env` → 在 `.env` 填機密 → `bash scripts/migrate_secrets.sh` → `docker compose up -d`。
- `CODEBASE.md`：環境變數清單拆兩欄；檔案地圖加 `scripts/migrate_secrets.sh` 一行；`docker-compose.yml` 說明加 secrets；`autofix/bin/probe` 那行註明帳密來自 secrets 檔。
- `AGENTS.md` §1「新環境變數寫進 .env 卻進不了容器」那條末尾加一句：「機密（清單見 `app_secrets.py` 用法與 compose `secrets:`）不走這條，見下一條。」並在其後新增一條：

```markdown
### 🔴 坑：新增機密是「三個地方」的事，少一個就靜默失效或整個起不來
- **規則**：機密不放 `.env`、不進 `environment:`。新增一個機密要：① `~/.config/money-bot/secrets/<小寫名>`（600，選填也要建空檔）② `docker-compose.yml` 頂層 `secrets:` 與 app 服務 `secrets:` 兩處 ③ 程式用 `app_secrets.get_secret("NAME")`，並把名稱加進 `tests/test_secrets_guard.py` 的 `SECRET_NAMES` 與 `scripts/migrate_secrets.sh` 的 `NAMES`。
- **為什麼**：環境變數會被 codex / Playwright 子程序繼承、`docker inspect` 看得到明文；`.env` 在 live-mount 的 `/app` 下，容器裡誰都讀得到。
- **compose 的脾氣**：file 型 secret 檔案不存在 → 整個 stack 起不來（不是只有那個功能失效）。
- **殘餘風險**：codex 的唯讀沙箱只擋寫不擋讀，它仍讀得到 `/run/secrets`；要徹底隔離得讓 codex 換 UID 跑（未做）。主機或容器 root 被拿下時 secrets 照樣可讀。
- **驗收**：`docker exec money-bot ls /run/secrets`；`docker exec money-bot cat /proc/1/environ | tr '\0' '\n' | grep -c -E 'TOKEN|KEY|PASSWORD|DATABASE_URL'` 應為 0。
```

- [ ] **Step 8: Commit**

```bash
git add scripts/migrate_secrets.sh tests/test_migrate_secrets.py docker-compose.yml autofix/bin/probe .env.example README.md CODEBASE.md AGENTS.md
git commit -m "feat(secrets): compose 改掛 secrets、新增 migrate_secrets.sh、probe 改讀 secrets 檔；文件更新"
```

---

## 上線（不派工；指揮者與用戶在主機執行，見 spec §6）

1. 三個 Task 都 PASS 並 merge 到 master；`scripts/check_tests.sh` 在 master 全過；`docker exec -w /app money-bot python -c "import main"`。
2. `bash scripts/migrate_secrets.sh`（用戶在場）。
3. `docker compose up -d`，確認輸出是 `Recreated`；輪詢 log 到 `Application startup complete`。
4. 驗證 spec §6 第 5 點全部項目；通過後用戶確認刪除 `~/.config/money-bot/env.bak.*`。
