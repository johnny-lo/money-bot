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
  # 重複的 key：docker compose 的 dotenv 取最後一筆，這裡照辦
  line=$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n1) || return 0
  [ -n "$line" ] || return 0
  v=${line#*=}
  v=${v%$'\r'}
  # `KEY=   # 註解`：= 後至少一個空白再接 #，值是空的（在去空白前判斷；`KEY=#abc` 的 # 是值）
  case "$v" in
    [[:space:]]*) [[ "$v" =~ ^[[:space:]]+# ]] && { printf ''; return 0; } ;;
  esac
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
# mktemp 保證檔名唯一（同一秒跑兩次也不會蓋掉搬遷前的備份）
bak="$(mktemp "$(dirname "$DEST")/env.bak.$(date +%Y%m%d-%H%M%S).XXXXXX")"
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
