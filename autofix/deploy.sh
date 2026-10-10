#!/usr/bin/env bash
# 一次處理一個 approved 檔：.abandon → 清理；.deploy → 前置檢查 → merge → 預檢/測試 → 重啟 → 驗證；失敗回滾。
set -uo pipefail
REPO="${AUTOFIX_REPO:-$HOME/Desktop/linebot}"; AF="$REPO/autofix"
f=$(ls -1tr "$AF"/approved/* 2>/dev/null | head -1 || true)
[ -n "$f" ] || exit 0
name=$(basename "$f"); id="${name%%.*}"; action="${name##*.}"
rm -f "$f"
# worktree 放在家目錄以外：Claude 的讀取權限是黑名單制，放外面才能整個 deny //home/**
WT="${AUTOFIX_WT_ROOT:-/var/tmp}/linebot-autofix-$id"; BR="autofix/$id"
DRY="${AUTOFIX_DRY_RUN:-}"
TARGET="${AUTOFIX_DEPLOY_BRANCH:-master}"

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
# 連按兩次：第二個核可檔進來時，分支早就合進去（或部署成功後已刪除）→ 什麼都別做、也別發卡
# （否則 merge 找不到分支會被誤報成「合併衝突」，還把事件改回 reported）
git rev-parse --verify -q "refs/heads/$BR" >/dev/null || exit 0
if git merge-base --is-ancestor "$BR" HEAD 2>/dev/null; then exit 0; fi
cur=$(git rev-parse --abbrev-ref HEAD)
if [ "$cur" != "$TARGET" ]; then
  emit reported precheck "正式目錄目前在 $cur 分支，不是 $TARGET，沒有部署。切回 $TARGET 後再按一次。"; exit 0
fi
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
  trap - TERM
  local note
  if git revert -m 1 --no-edit "$merge_sha" >/tmp/af-revert-$id.log 2>&1; then
    note="已 revert 並重啟回到合併前"
  else
    # 卡片絕不能在 revert 失敗時說「已回滾」——那會讓人以為正式環境復原了
    git revert --abort >/dev/null 2>&1
    note="⚠️ revert 失敗，正式目錄仍是合併後的狀態（$merge_sha），請立刻開 session 處理"
  fi
  if [ -z "$DRY" ]; then local t; t=$(date -Iseconds); docker restart money-bot >/dev/null; wait_ready "$t"; fi
  emit failed "$1" "$2，$note" "$3
$(cat /tmp/af-revert-$id.log 2>/dev/null)"; exit 0; }
# systemd 逾時會送 SIGTERM：合併後被砍＝半套上線，一樣要回滾並發卡
trap 'rollback timeout "部署逾時被中止" ""' TERM

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
