"""自動修復的決策核心（純函式）：何時計次、何時派發、何時冷卻、何時升級人工。"""
from datetime import datetime, timedelta

from autofix.policy import (
    Policy, Snapshot, decide, merge_context, POLICIES, RECUR_WINDOW,
)
from models import AutofixIncident

NOW = datetime(2026, 10, 10, 21, 0)
P3 = Policy(threshold=3, window=None)


def test_model_欄位():
    cols = set(AutofixIncident.__table__.columns.keys())
    assert {"sensor", "signature", "status", "hit_keys", "context", "verdict",
            "report_message_id", "reported_at", "closed_at"} <= cols


def test_第一次命中_建立計數中事件():
    d = decide(None, "2026-10-10", NOW, P3)
    assert d.action == "new" and [k for k, _ in d.hit_keys] == ["2026-10-10"]


def test_門檻1_第一次就派發():
    assert decide(None, "x", NOW, Policy(1, None)).action == "dispatch"


def test_同一去重鍵不重複計():
    s = Snapshot("counting", [["2026-10-10", NOW.isoformat()]], None)
    d = decide(s, "2026-10-10", NOW, P3)
    assert d.action == "count" and len(d.hit_keys) == 1


def test_第三個不同鍵_派發():
    s = Snapshot("counting", [["2026-10-08", "x"], ["2026-10-09", "x"]], None)
    assert decide(s, "2026-10-10", NOW, P3).action == "dispatch"


def test_處理中的事件_不重複派發():
    for st in ("dispatched", "reported", "deploying"):
        assert decide(Snapshot(st, [], None), "k", NOW, P3).action == "noop"


def test_時間窗外的命中被剪掉():
    p = Policy(3, timedelta(days=7))
    old = (NOW - timedelta(days=8)).isoformat()
    s = Snapshot("counting", [["u1", old], ["u2", NOW.isoformat()]], None)
    d = decide(s, "u3", NOW, p)
    assert d.action == "count" and [k for k, _ in d.hit_keys] == ["u2", "u3"]


def test_修好後7天內再犯_升級人工():
    s = Snapshot("resolved", [], NOW - timedelta(days=2))
    assert decide(s, "k", NOW, P3).action == "escalate"


def test_修好超過7天再犯_當新事件():
    s = Snapshot("resolved", [], NOW - RECUR_WINDOW - timedelta(hours=1))
    assert decide(s, "k", NOW, P3).action == "new"


def test_人工結案7天內再犯_冷卻不吵():
    for st in ("needs_human", "inconclusive", "failed", "abandoned"):
        s = Snapshot(st, [], NOW - timedelta(days=1))
        assert decide(s, "k", NOW, P3).action == "noop"


def test_merge_context_清單聯集保序且有上限_其他覆蓋():
    old = {"urls": ["a", "b"], "error": "舊"}
    new = {"urls": ["b", "c"], "error": "新"}
    assert merge_context(old, new) == {"urls": ["a", "b", "c"], "error": "新"}
    many = merge_context({"urls": [str(i) for i in range(10)]}, {"urls": ["x"]}, cap=10)
    assert len(many["urls"]) == 10 and many["urls"][-1] == "x"


def test_各感測器門檻():
    assert POLICIES["einvoice_login"].threshold == 3
    assert POLICIES["scheduler_job"].threshold == 3
    assert POLICIES["link_extract"] == Policy(3, timedelta(days=7))
    assert POLICIES["drill"].threshold == 1
