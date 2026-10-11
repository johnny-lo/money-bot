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
