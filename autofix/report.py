"""驗證 Claude 的報告、組 outbox 訊息（主機 python3 執行 → 只准標準函式庫）。

原則：Claude 說 fixed 不算數，要有證據——測試全綠、分支上真的有 commit、沒碰禁區。
任何一項不成立就降級 inconclusive 並寫明原因，報告卡上就不會出現部署鈕。
"""
import argparse
import json
import subprocess
import sys

VERDICTS = {"fixed", "needs_human", "inconclusive"}
FORBIDDEN_PREFIXES = ("frontend/", "autofix/", "scripts/systemd/", ".env")
FORBIDDEN_FILES = {"Dockerfile", "docker-compose.yml"}
DEFAULTS = {"root_cause": "", "evidence": [], "fix_summary": "", "probe": "", "risk": "",
            "questions_for_human": []}


def forbidden(files: list[str]) -> list[str]:
    return [f for f in files if f in FORBIDDEN_FILES or f.startswith(FORBIDDEN_PREFIXES)]


def validate(raw, *, files_changed: list[str], fix_commits: int) -> dict:
    if not isinstance(raw, dict):
        return {**DEFAULTS, "verdict": "inconclusive", "tests": {"passed": 0, "failed": 0},
                "downgraded": ["Claude 沒有產出報告（逾時、回合用完或崩潰）"]}
    r = {**DEFAULTS, **{k: raw[k] for k in DEFAULTS if k in raw}}
    t = raw.get("tests") if isinstance(raw.get("tests"), dict) else {}
    r["tests"] = {"passed": int(t.get("passed") or 0), "failed": int(t.get("failed") or 0)}
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
    files = [x for x in _git(a.worktree, "diff", "--name-only", rng).splitlines() if x]
    commits = len([x for x in _git(a.worktree, "rev-list", rng).splitlines() if x])
    report = validate(raw, files_changed=files, fix_commits=commits)
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
    for k in ("--id", "--worktree", "--branch", "--base", "--claude-out", "--superpowers", "--title", "--af"):
        ap.add_argument(k, required=True)
    json.dump(finalize(ap.parse_args()), sys.stdout, ensure_ascii=False)
