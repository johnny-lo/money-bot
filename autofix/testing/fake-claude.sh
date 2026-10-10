#!/usr/bin/env bash
# DRY_RUN 用假 claude：在 worktree 做一個無害 commit 並寫 fixed 報告。
set -e
echo "# dry-run $(date +%s)" >> AGENTS.md
git commit -qam "fix(autofix): dry-run 假修正"
cat > .autofix-report.json <<'EOF'
{"verdict":"fixed","root_cause":"dry-run","evidence":["dry-run"],"fix_summary":"dry-run",
 "tests":{"passed":1,"failed":0},"probe":"dry-run","risk":"無","questions_for_human":[]}
EOF
echo '{"session_id":"dry-run-session"}'
