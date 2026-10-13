from autofix.report import validate, forbidden

GOOD = {"verdict": "fixed", "root_cause": "r", "evidence": ["e"], "fix_summary": "f",
        "tests": {"passed": 580, "failed": 0}, "probe": "ok", "risk": "低",
        "questions_for_human": []}


def test_合格的_fixed_原樣通過():
    r = validate(GOOD, files_changed=["einvoice.py"], fix_commits=1)
    assert r["verdict"] == "fixed" and not r.get("downgraded")


def test_沒有報告_inconclusive():
    r = validate(None, files_changed=[], fix_commits=0)
    assert r["verdict"] == "inconclusive" and "沒有產出報告" in r["downgraded"][0]


def test_宣稱修好但測試失敗_降級():
    r = validate({**GOOD, "tests": {"passed": 5, "failed": 2}}, files_changed=["a.py"], fix_commits=1)
    assert r["verdict"] == "inconclusive" and any("測試" in x for x in r["downgraded"])


def test_宣稱修好但沒有_commit_降級():
    r = validate(GOOD, files_changed=[], fix_commits=0)
    assert r["verdict"] == "inconclusive"


def test_改到禁區_降級():
    r = validate(GOOD, files_changed=["einvoice.py", "frontend/src/App.jsx"], fix_commits=1)
    assert r["verdict"] == "inconclusive" and "frontend/src/App.jsx" in r["downgraded"][0]


def test_未知結論_降級_且缺欄位補預設():
    r = validate({"verdict": "maybe"}, files_changed=[], fix_commits=0)
    assert r["verdict"] == "inconclusive"
    assert r["evidence"] == [] and r["tests"] == {"passed": 0, "failed": 0}


def test_needs_human_不檢查測試():
    r = validate({**GOOD, "verdict": "needs_human", "tests": {}}, files_changed=[], fix_commits=0)
    assert r["verdict"] == "needs_human"


def test_forbidden():
    assert forbidden(["Dockerfile", "docker-compose.yml", ".env.example", "autofix/run.sh",
                      "scripts/systemd/x.service", "food/ingest.py"]) == [
        "Dockerfile", "docker-compose.yml", ".env.example", "autofix/run.sh",
        "scripts/systemd/x.service"]


# ── 測試結果來源與禁區 ────────────────────────────────────────
from autofix.report import parse_test_log, deleted_tests


def test_以主機實跑的測試為準_不信_Claude_自報():
    claimed_green = {**GOOD, "tests": {"passed": 999, "failed": 0}}
    r = validate(claimed_green, files_changed=["a.py"], fix_commits=1,
                 real_tests={"passed": 600, "failed": 2})
    assert r["tests"] == {"passed": 600, "failed": 2}
    assert r["verdict"] == "inconclusive"


def test_parse_test_log():
    assert parse_test_log("IMPORT_OK\n640 passed, 3 warnings in 4.0s") == {"passed": 640, "failed": 0}
    assert parse_test_log("IMPORT_OK\n2 failed, 638 passed in 4s") == {"passed": 638, "failed": 2}
    # import 預檢沒過：一個測試都沒跑，必須算失敗
    assert parse_test_log("ModuleNotFoundError: x")["failed"] >= 1
    assert parse_test_log("")["failed"] >= 1


def test_禁區補上_claude_設定與_git_檔():
    assert forbidden([".claude/settings.json", ".gitignore", ".gitattributes", "einvoice.py"]) == [
        ".claude/settings.json", ".gitignore", ".gitattributes"]


def test_刪掉的測試檔要被點名():
    lines = ["M\teinvoice.py", "D\ttests/test_einvoice_login_landing.py", "D\tdocs/x.md"]
    assert deleted_tests(lines) == ["tests/test_einvoice_login_landing.py"]


def test_刪測試檔的修正_要人看一眼():
    r = validate(GOOD, files_changed=["einvoice.py"], fix_commits=1,
                 deleted=["tests/test_x.py"])
    assert any("tests/test_x.py" in q for q in r["questions_for_human"])
