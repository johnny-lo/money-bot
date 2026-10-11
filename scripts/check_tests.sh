#!/usr/bin/env bash
# Thoth 的 approved check：在「目前目錄」（任務 worktree）跑 import 預檢＋全套測試。
# 跟 autofix/bin/test 同一招：一次性容器掛 worktree 為 /app，配一個拋棄式 Postgres
# （--internal 網路，不能對外、也連不到正式 DB）。不掛 /run/secrets、不帶任何真金鑰。
# 不能用 `docker exec money-bot`——那跑的是主目錄 /app，不是 worktree 的程式碼。
set -euo pipefail
WT="$(pwd)"
[ -f "$WT/main.py" ] || { echo "請在 repo 或 worktree 根目錄執行" >&2; exit 2; }
tag="chk-$(basename "$WT" | tr -c 'a-zA-Z0-9_.-' '-' | cut -c1-40)-$$"
cleanup() { docker rm -f "$tag-db" >/dev/null 2>&1 || true; docker network rm "$tag" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$tag" >/dev/null
docker run -d --name "$tag-db" --network "$tag" -e POSTGRES_PASSWORD=t -e POSTGRES_USER=t -e POSTGRES_DB=t postgres:15-alpine >/dev/null
for _ in $(seq 1 30); do docker exec "$tag-db" pg_isready -U t >/dev/null 2>&1 && break; sleep 1; done
# 容器是 root：結束前把 worktree 擁有者還給主機使用者，否則 root 擁有的 __pycache__ 讓 git worktree remove 失敗
docker run --rm --network "$tag" -v "$WT":/app -w /app \
  -e DATABASE_URL="postgresql://t:t@$tag-db:5432/t" -e OWNER="$(id -u):$(id -g)" money-bot \
  sh -c 'python -c "import main" >/dev/null && echo "IMPORT_OK" && python -m pytest tests/ -q -p no:cacheprovider; rc=$?; chown -R "$OWNER" /app; exit $rc'
