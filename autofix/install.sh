#!/usr/bin/env bash
# 建交接目錄（必須由主機使用者建立）＋安裝 systemd user units。
set -euo pipefail
AF="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$AF")"
mkdir -p "$AF"/{inbox,approved,outbox,state}
[ "${1:-}" = "--dirs-only" ] && exit 0
mkdir -p "$HOME/.config/systemd/user"
for u in linebot-autofix-inbox.path linebot-autofix-run.service linebot-autofix-deploy.path linebot-autofix-deploy.service; do
  ln -sf "$REPO/scripts/systemd/$u" "$HOME/.config/systemd/user/$u"
done
systemctl --user daemon-reload
systemctl --user enable --now linebot-autofix-inbox.path linebot-autofix-deploy.path
systemctl --user list-units 'linebot-autofix-*' --no-pager
