#!/usr/bin/env bash
# 一次處理一個 inbox 事件（systemd path unit 在 inbox 還有檔時會再觸發）。
set -euo pipefail
REPO="${AUTOFIX_REPO:-$HOME/Desktop/linebot}"
AF="$REPO/autofix"
DRY="${AUTOFIX_DRY_RUN:-}"
f=$(ls -1tr "$AF"/inbox/*.json 2>/dev/null | head -1 || true)
[ -n "$f" ] || exit 0
id=$(basename "$f" .json)
inbox="$AF/state/$id.inbox.json"
title="(讀不到事件標題)"

emit() { # $1=json 檔內容 → outbox（原子）
  printf '%s' "$1" > "$AF/outbox/.$id-$2.tmp" && mv "$AF/outbox/.$id-$2.tmp" "$AF/outbox/$id-$2.json"; }

# 事件一搬出 inbox，之後任何一步失敗（含 systemd 逾時送 SIGTERM）都要發卡，
# 不然事件卡在 dispatched、這個簽名的感測器永遠失聲。
on_fail() {
  trap - ERR TERM
  python3 - "$id" "$title" "$1" "$(tail -c 800 "$AF/state/$id.claude.err" 2>/dev/null)" > "$AF/outbox/.$id-report.tmp" <<'PY'
import json, sys
i, title, where, err = sys.argv[1:5]
print(json.dumps({"type": "report", "incident_id": int(i), "title": title, "diff_file": None,
                  "diff_stat": "", "session_id": None, "superpowers_version": "?",
                  "report": {"verdict": "inconclusive", "root_cause": "", "evidence": [err] if err else [],
                             "fix_summary": "", "files_changed": [], "tests": {"passed": 0, "failed": 0},
                             "probe": "", "risk": "", "questions_for_human": [],
                             "downgraded": [f"autofix/run.sh {where} 失敗，Claude 沒有跑完（看 journalctl --user -u linebot-autofix-run）"]}},
                 ensure_ascii=False))
PY
  mv "$AF/outbox/.$id-report.tmp" "$AF/outbox/$id-report.json"
}

mv "$f" "$inbox"
trap 'on_fail "第 $LINENO 行"' ERR
trap 'on_fail "被中止（逾時/SIGTERM）"; exit 1' TERM

field() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$inbox" "$1"; }
sensor=$(field sensor); title=$(field title); escalated=$(field escalated)

if [ "$escalated" = "True" ]; then
  emit "$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps({"type":"escalated","incident_id":d["id"],"title":d["title"],"context":d["context"]},ensure_ascii=False))' "$inbox")" escalated
  exit 0
fi

# worktree 放在家目錄以外：Claude 的讀取權限是黑名單制，放外面才能整個 deny //home/**
WT="${AUTOFIX_WT_ROOT:-/var/tmp}/linebot-autofix-$id"; BR="autofix/$id"
git -C "$REPO" worktree add -q "$WT" -b "$BR"
if [ "$sensor" = drill ]; then
  git -C "$WT" apply "$AF/drill.patch"
  git -C "$WT" commit -qam "drill: 故意弄壞 _login_landing（演習）"
fi
base=$(git -C "$WT" rev-parse HEAD)   # drill commit 之後才記 base → base..branch 只算 Claude 的修正
sed -e "s#__AF__#$AF#g" -e "s#__REPO__#$REPO#g" -e "s#__WT__#$WT#g" -e "s#__HOME__#$HOME#g" \
  "$AF/claude-settings.template.json" > "$AF/state/$id.settings.json"
prompt=$(cd "$REPO" && python3 -m autofix.prompt "$inbox" "$AF")
CLAUDE=claude; [ "$DRY" = 1 ] && CLAUDE="$AF/testing/fake-claude.sh"
( cd "$WT" && timeout 45m "$CLAUDE" -p "$prompt" --max-turns 60 --output-format json \
    --permission-mode acceptEdits --settings "$AF/state/$id.settings.json" < /dev/null ) \
  > "$AF/state/$id.claude.json" 2> "$AF/state/$id.claude.err" || true

# 測試結果以主機自己跑的為準——Claude 報告裡的數字只是它的說法
if [ "$DRY" = 1 ]; then
  printf 'IMPORT_OK\n1 passed in 0.1s\n' > "$AF/state/$id.test.log"
else
  ( cd "$WT" && timeout 10m "$AF/bin/test" ) > "$AF/state/$id.test.log" 2>&1 || true
fi

sp=$(ls -1 "$HOME/.claude/plugins/cache/claude-plugins-official/superpowers/" 2>/dev/null | sort -V | tail -1 || true)
out=$(cd "$REPO" && python3 -m autofix.report finalize --id "$id" --worktree "$WT" --branch "$BR" \
        --base "$base" --claude-out "$AF/state/$id.claude.json" --superpowers "${sp:-?}" \
        --title "$title" --af "$AF" --test-log "$AF/state/$id.test.log")
emit "$out" report
