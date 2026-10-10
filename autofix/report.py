"""驗證 Claude 的報告、組 outbox 訊息（主機 python3 執行 → 只准標準函式庫）。

原則：Claude 說 fixed 不算數，要有證據——測試全綠、分支上真的有 commit、沒碰禁區。
任何一項不成立就降級 inconclusive 並寫明原因，報告卡上就不會出現部署鈕。
"""
import argparse
import json
import re
import subprocess
import sys

VERDICTS = {"fixed", "needs_human", "inconclusive"}
# .claude/：commit 進去的 settings/hooks 會合併進正式目錄，在使用者自己的 session 裡執行
FORBIDDEN_PREFIXES = ("frontend/", "autofix/", "scripts/systemd/", ".env", ".claude/", ".git")
FORBIDDEN_FILES = {"Dockerfile", "docker-compose.yml"}
DEFAULTS = {"root_cause": "", "evidence": [], "fix_summary": "", "probe": "", "risk": "",
            "questions_for_human": []}


def forbidden(files: list[str]) -> list[str]:
    return [f for f in files if f in FORBIDDEN_FILES or f.startswith(FORBIDDEN_PREFIXES)]


def parse_test_log(log: str) -> dict:
    """bin/test 的輸出 → {passed, failed}。import 預檢沒過＝一個都沒跑，算失敗。"""
    if "IMPORT_OK" not in (log or ""):
        return {"passed": 0, "failed": 1}
    p = re.search(r"(\d+) passed", log)
    f = re.search(r"(\d+) (?:failed|error)", log)
    return {"passed": int(p.group(1)) if p else 0, "failed": int(f.group(1)) if f else 0}


def deleted_tests(name_status: list[str]) -> list[str]:
    """git diff --name-status 的行 → 被刪掉的測試檔。"""
    out = []
    for line in name_status:
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] == "D" and parts[1].startswith("tests/"):
            out.append(parts[1])
    return out


def validate(raw, *, files_changed: list[str], fix_commits: int,
             real_tests: dict | None = None, deleted: list[str] | None = None) -> dict:
    """real_tests＝主機在 worktree 實跑 bin/test 的結果；有給就以它為準（Claude 自報的不算數）。"""
    if not isinstance(raw, dict):
        return {**DEFAULTS, "verdict": "inconclusive", "tests": {"passed": 0, "failed": 0},
                "downgraded": ["Claude 沒有產出報告（逾時、回合用完或崩潰）"]}
    r = {**DEFAULTS, **{k: raw[k] for k in DEFAULTS if k in raw}}
    t = raw.get("tests") if isinstance(raw.get("tests"), dict) else {}
    r["tests"] = {"passed": int(t.get("passed") or 0), "failed": int(t.get("failed") or 0)}
    if real_tests is not None:
        r["tests"] = dict(real_tests)
    if deleted:
        r["questions_for_human"] = list(r["questions_for_human"]) + [
            "這個修正刪掉了測試檔，確認是合理的再部署：" + "、".join(deleted)]
    r["verdict"] = raw.get("verdict")
    problems = []
    if r["verdict"] not in VERDICTS:
        problems.append(f"未知的結論 {r['verdict']!r}")
    elif r["verdict"] == "fixed":
        if r["tests"]["failed"] or not r["tests"]["passed"]:
            problems.append(f"測試不是全綠（{r['tests']['passed']} passed / {r['tests']['failed']} failed）")
        if fix_commits < 1:
            problems.append("修正分支上沒有任何 commit")
        bad = forbidden(files_changed)
        if bad:
            problems.append("改到禁區：" + "、".join(bad))
    if problems:
        r["verdict"] = "inconclusive"
        r["downgraded"] = problems
    return r


def _git(wt: str, *args: str) -> str:
    return subprocess.run(["git", "-C", wt, *args], capture_output=True, text=True).stdout


def finalize(a) -> dict:
    try:
        with open(f"{a.worktree}/.autofix-report.json", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = None
    rng = f"{a.base}..{a.branch}"
    # --no-renames：rename 偵測開著的話，`git mv autofix/x.py y.py` 只會列出 y.py，禁區檢查就被繞過
    status = [x for x in _git(a.worktree, "diff", "--no-renames", "--name-status", rng).splitlines() if x]
    files = [x.split("\t", 1)[1] for x in status if "\t" in x]
    commits = len([x for x in _git(a.worktree, "rev-list", rng).splitlines() if x])
    try:
        with open(a.test_log, encoding="utf-8") as f:
            real = parse_test_log(f.read())
    except OSError:
        real = {"passed": 0, "failed": 1}
    report = validate(raw, files_changed=files, fix_commits=commits,
                      real_tests=real, deleted=deleted_tests(status))
    report["files_changed"] = files
    diff_rel = None
    if files:
        diff_rel = f"autofix/state/{a.id}.diff"
        with open(f"{a.af}/state/{a.id}.diff", "w", encoding="utf-8") as f:
            f.write(_git(a.worktree, "diff", rng))
    session_id = None
    try:
        with open(a.claude_out, encoding="utf-8") as f:
            session_id = json.load(f).get("session_id")
    except (OSError, ValueError):
        pass
    return {"type": "report", "incident_id": int(a.id), "title": a.title, "report": report,
            "diff_stat": _git(a.worktree, "diff", "--stat", rng).strip()[-900:],
            "diff_file": diff_rel, "session_id": session_id,
            "superpowers_version": a.superpowers}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["finalize"])
    for k in ("--id", "--worktree", "--branch", "--base", "--claude-out", "--superpowers", "--title", "--af",
              "--test-log"):
        ap.add_argument(k, required=True)
    json.dump(finalize(ap.parse_args()), sys.stdout, ensure_ascii=False)
