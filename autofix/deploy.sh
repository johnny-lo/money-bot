#!/usr/bin/env bash
# 一次處理一個 approved 檔：.abandon → 清理；.deploy → 前置檢查 → merge → 預檢/測試 → 重啟 → 驗證；失敗回滾。
set -uo pipefail
REPO="${AUTOFIX_REPO:-$HOME/Desktop/linebot}"; AF="$REPO/autofix"
f=$(ls -1tr "$AF"/approved/* 2>/dev/null | head -1 || true)
[ -n "$f" ] || exit 0
name=$(basename "$f"); id="${name%%.*}"; action="${name##*.}"
rm -f "$f"
WT="$(dirname "$REPO")/linebot-autofix-$id"; BR="autofix/$id"
DRY="${AUTOFIX_DRY_RUN:-}"

cleanup_branch() {
  # 保險：worktree 裡若殘留容器（root）寫的檔，先還給主機使用者，不然 worktree remove 會失敗
  [ -d "$WT" ] && [ -z "$DRY" ] && docker run --rm -v "$WT":/w money-bot chown -R "$(id -u):$(id -g)" /w >/dev/null 2>&1
  git -C "$REPO" worktree remove --force "$WT" 2>/dev/null; git -C "$REPO" branch -D "$BR" >/dev/null 2>&1; }
emit() { # status stage message [log_tail]
  python3 - "$id" "$1" "$2" "$3" "${4:-}" > "$AF/outbox/.$id-deploy.tmp" <<'PY'
import json, sys
i, st, stage, msg, tail = sys.argv[1:6]
print(json.dumps({"type": "deploy", "incident_id": int(i), "status": st, "stage": stage,
                  "message": msg, "log_tail": tail[-1500:]}, ensure_ascii=False))
PY
  mv "$AF/outbox/.$id-deploy.tmp" "$AF/outbox/$id-deploy.json"; }

if [ "$action" = abandon ]; then cleanup_branch; exit 0; fi

cd "$REPO"
if [ -n "$(git status --porcelain)" ]; then
  emit reported precheck "正式目錄有未提交的改動，沒有部署。commit 或 stash 後再按一次。" "$(git status --short | head -20)"; exit 0
fi
if ! git merge --no-ff --no-edit "$BR" >/tmp/af-merge-$id.log 2>&1; then
  git merge --abort 2>/dev/null
  emit reported precheck "合併有衝突，沒有部署（master 在事件之後有變動）。請開 session 處理。" "$(cat /tmp/af-merge-$id.log)"; exit 0
fi
merge_sha=$(git rev-parse HEAD)

wait_ready() { # 等 startup complete，最多 180 秒
  local since=$1
  for _ in $(seq 1 90); do
    docker logs --since "$since" money-bot 2>&1 | grep -q "Application startup complete" && return 0
    sleep 2
  done; return 1; }

rollback() { # stage message log
  git revert -m 1 --no-edit "$merge_sha" >/dev/null 2>&1
  if [ -z "$DRY" ]; then local t; t=$(date -Iseconds); docker restart money-bot >/dev/null; wait_ready "$t"; fi
  emit failed "$1" "$2，已 revert 並重啟回到合併前" "$3"; exit 0; }

run() { [ -n "$DRY" ] && { echo "DRY: $*"; return 0; }; "$@"; }

log=$(run docker exec -w /app money-bot python -c "import main" 2>&1) || rollback import "import 預檢失敗" "$log"
log=$(run docker exec -w /app money-bot python -m pytest tests/ -q 2>&1) || rollback tests "全套測試失敗" "$(echo "$log" | tail -30)"
if [ -z "$DRY" ]; then
  t=$(date -Iseconds); docker restart money-bot >/dev/null
  wait_ready "$t" || rollback startup "重啟後 3 分鐘內沒有 startup complete" "$(docker logs --since "$t" money-bot 2>&1 | tail -30)"
fi
log=$(run docker exec -w /app money-bot python -m autofix.verify "$id" 2>&1) || rollback verify "上線驗證失敗" "$log"
cleanup_branch
emit resolved verify "${log:-已上線}"
