from discordbot.embeds import autofix_report_embed, autofix_deploy_embed, autofix_escalated_embed

REPORT = {
    "type": "report", "incident_id": 7, "title": "載具1 發票登入連續失敗",
    "report": {"verdict": "fixed", "root_cause": "登入後被導去資料設定頁",
               "evidence": ["URL=btc508w"], "fix_summary": "改走查詢頁",
               "files_changed": ["einvoice.py"], "tests": {"passed": 580, "failed": 0},
               "probe": "登入 1 次成功，抓到 8 張", "risk": "低", "questions_for_human": []},
    "diff_stat": " einvoice.py | 10 +++", "diff_file": "autofix/state/7.diff",
    "session_id": "abc-123", "superpowers_version": "6.4.1",
}


def _fields(e):
    return {f.name: f.value for f in e.fields}


def test_fixed_報告卡():
    e = autofix_report_embed(REPORT)
    assert "✅" in e.title and "#7" in e.title
    f = _fields(e)
    assert "登入後被導去資料設定頁" in f["根因"]
    assert "580" in f["測試"] and "claude --resume abc-123" in f["接手"]


def test_needs_human_顯示待你決定的事():
    m = {**REPORT, "report": {**REPORT["report"], "verdict": "needs_human",
                              "questions_for_human": ["請到財政部網站換密碼"]}}
    e = autofix_report_embed(m)
    assert "🙋" in e.title and "請到財政部網站換密碼" in _fields(e)["需要你決定"]


def test_降級原因要顯示():
    m = {**REPORT, "report": {**REPORT["report"], "verdict": "inconclusive",
                              "downgraded": ["測試有 2 個失敗"]}}
    assert "測試有 2 個失敗" in _fields(autofix_report_embed(m))["降級原因"]


def test_欄位超長會截斷():
    m = {**REPORT, "report": {**REPORT["report"], "root_cause": "長" * 3000}}
    assert all(len(f.value) <= 1024 for f in autofix_report_embed(m).fields)


def test_部署結果卡():
    ok = autofix_deploy_embed({"type": "deploy", "incident_id": 7, "status": "resolved",
                               "stage": "verify", "message": "上線驗證通過", "log_tail": ""})
    assert "🚀" in ok.title
    bad = autofix_deploy_embed({"type": "deploy", "incident_id": 7, "status": "failed",
                                "stage": "tests", "message": "測試失敗，已回滾", "log_tail": "E assert"})
    assert "↩️" in bad.title and "E assert" in bad.description


def test_升級卡():
    e = autofix_escalated_embed({"type": "escalated", "incident_id": 9,
                                 "title": "[上次修正無效] 載具1 發票登入連續失敗", "context": {}})
    assert "上次修正無效" in e.title
