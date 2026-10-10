#!/usr/bin/env bash
# 一次處理一個 inbox 事件（systemd path unit 在 inbox 還有檔時會再觸發）。
set -euo pipefail
REPO="${AUTOFIX_REPO:-$HOME/Desktop/linebot}"
AF="$REPO/autofix"
f=$(ls -1tr "$AF"/inbox/*.json 2>/dev/null | head -1 || true)
[ -n "$f" ] || exit 0
id=$(basename "$f" .json)
mv "$f" "$AF/state/$id.inbox.json"
inbox="$AF/state/$id.inbox.json"
field() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$inbox" "$1"; }
sensor=$(field sensor); title=$(field title); escalated=$(field escalated)

emit() { # $1=json 檔內容 → outbox（原子）
  printf '%s' "$1" > "$AF/outbox/.$id-$2.tmp" && mv "$AF/outbox/.$id-$2.tmp" "$AF/outbox/$id-$2.json"; }

if [ "$escalated" = "True" ]; then
  emit "$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps({"type":"escalated","incident_id":d["id"],"title":d["title"],"context":d["context"]},ensure_ascii=False))' "$inbox")" escalated
  exit 0
fi

WT="$(dirname "$REPO")/linebot-autofix-$id"; BR="autofix/$id"
git -C "$REPO" worktree add -q "$WT" -b "$BR"
if [ "$sensor" = drill ]; then
  git -C "$WT" apply "$AF/drill.patch"
  git -C "$WT" commit -qam "drill: 故意弄壞 _login_landing（演習）"
fi
base=$(git -C "$WT" rev-parse HEAD)   # drill commit 之後才記 base → base..branch 只算 Claude 的修正
sed "s#__AF__#$AF#g" "$AF/claude-settings.template.json" > "$AF/state/$id.settings.json"
prompt=$(cd "$REPO" && python3 -m autofix.prompt "$inbox" "$AF")
CLAUDE=claude; [ "${AUTOFIX_DRY_RUN:-}" = 1 ] && CLAUDE="$AF/testing/fake-claude.sh"
( cd "$WT" && timeout 45m "$CLAUDE" -p "$prompt" --max-turns 60 --output-format json \
    --permission-mode acceptEdits --settings "$AF/state/$id.settings.json" ) \
  > "$AF/state/$id.claude.json" 2> "$AF/state/$id.claude.err" || true
sp=$(ls -1 "$HOME/.claude/plugins/cache/claude-plugins-official/superpowers/" 2>/dev/null | sort -V | tail -1)
out=$(cd "$REPO" && python3 -m autofix.report finalize --id "$id" --worktree "$WT" --branch "$BR" \
        --base "$base" --claude-out "$AF/state/$id.claude.json" --superpowers "${sp:-?}" \
        --title "$title" --af "$AF")
emit "$out" report
