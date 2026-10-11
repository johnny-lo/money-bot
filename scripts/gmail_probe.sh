#!/usr/bin/env bash
# 開發用：在一次性容器跑 Gmail 探測腳本（扣款比對設計/除錯用）。
# 用法：scripts/gmail_probe.sh <probe.py>
#
# 邊界（主機端強制）：
# - 只掛 gmail_app_password、national_id 兩個 secret（唯讀），其他機密一律不帶。
# - 不接 compose 網路 → 連不到正式 DB；DATABASE_URL 指向不存在的位址。
# - probe 檔唯讀掛進容器、python -I 執行（不從 probe 所在目錄載入模組）。
# - repo 唯讀掛在 /repo：probe 要測專案程式時自行 sys.path.insert(0, "/repo")。
# ⚠️ 「IMAP 唯讀」是 probe 程式的慣例（select readonly=True / BODY.PEEK），不是這支腳本能強制的——
#   應用程式密碼本身有完整信箱權限。
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
probe="${1:-}"
[ -f "$probe" ] && [[ "$probe" == *.py ]] || { echo "用法：scripts/gmail_probe.sh <probe.py>" >&2; exit 2; }
probe="$(realpath "$probe")"
sdir="$HOME/.config/money-bot/secrets"
for k in gmail_app_password national_id; do
  [ -s "$sdir/$k" ] || { echo "secret $k 不存在或是空的" >&2; exit 2; }
done
addr="$(grep -E '^GMAIL_ADDRESS=' "$REPO/.env" | tail -1 | cut -d= -f2-)"
[ -n "$addr" ] || { echo ".env 沒有 GMAIL_ADDRESS" >&2; exit 2; }
shift
timeout 5m docker run --rm --entrypoint sh \
  -e GMAIL_ADDRESS="$addr" -e DATABASE_URL=postgresql://none:none@127.0.0.1:1/none \
  -v "$sdir/gmail_app_password":/run/secrets/gmail_app_password:ro \
  -v "$sdir/national_id":/run/secrets/national_id:ro \
  -v "$probe":/probe/probe.py:ro -v "$REPO":/repo:ro \
  money-bot -c 'pip install -q --disable-pip-version-check pypdf cryptography >/dev/null 2>&1; python -I /probe/probe.py "$@"' sh "$@"
