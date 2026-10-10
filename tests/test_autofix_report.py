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
