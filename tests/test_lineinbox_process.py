import json
from datetime import datetime
from pathlib import Path

import pytest

from cardrecon import repo as card_repo
from lineinbox import process
from lineinbox import repo as inbox_repo


FIXTURES = Path(__file__).parent / "fixtures" / "ctbc_line"
DB = object()


def _msg(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def rec(monkeypatch):
    """記下 handle 對兩個 repo 的呼叫順序；exists 與 upsert 的行為由各測試調。"""
    r = {"events": [], "exists": False, "upsert_error": None, "messages": []}

    def exists(db, message_id):
        assert db is DB
        return r["exists"]

    def save_message(db, m, status, error=None):
        assert db is DB
        r["events"].append(("save", m.message_id, status))
        r["messages"].append(m)
        return True

    def upsert_charges(db, message_id, charges):
        assert db is DB
        if r["upsert_error"]:
            raise r["upsert_error"]
        r["events"].append(("upsert", message_id, [c.amount for c in charges]))
        return len(charges)

    monkeypatch.setattr(inbox_repo, "exists", exists)
    monkeypatch.setattr(inbox_repo, "save_message", save_message)
    monkeypatch.setattr(card_repo, "upsert_charges", upsert_charges)
    return r


def _upserts(r):
    return [e for e in r["events"] if e[0] == "upsert"]


def test_實體店_先寫刷卡再存訊息(rec):
    assert process.handle(DB, _msg("store"), "ctbc") == "parsed"
    assert rec["events"] == [
        ("upsert", "line:900000000000000001", [1280]),
        ("save", "900000000000000001", "parsed"),
    ]


def test_入帳通知_只存訊息不寫刷卡(rec):
    assert process.handle(DB, _msg("deposit"), "ctbc") == "other"
    assert _upserts(rec) == []
    assert [e[2] for e in rec["events"]] == ["other"]
    assert rec["messages"][0].kind == "other"


def test_外幣_只存訊息不寫刷卡(rec):
    assert process.handle(DB, _msg("foreign_usd"), "ctbc") == "non_twd"
    assert _upserts(rec) == []
    assert [e[2] for e in rec["events"]] == ["non_twd"]
    assert rec["messages"][0].kind == "spend"


def test_版型壞掉_缺金額_等codex(rec):
    msg = _msg("store")
    flex = msg["contentMetadata"]["FLEX_JSON"]
    assert '"text": "NT$1,280"' in flex
    msg["contentMetadata"]["FLEX_JSON"] = flex.replace('"text": "NT$1,280"', '"text": ""')

    assert process.handle(DB, msg, "ctbc") == "needs_codex"
    assert _upserts(rec) == []
    assert [e[2] for e in rec["events"]] == ["needs_codex"]
    assert "NT$1,280" not in rec["messages"][0].texts


def test_已處理過_什麼都不寫(rec):
    rec["exists"] = True
    assert process.handle(DB, _msg("store"), "ctbc") is None
    assert rec["events"] == []


def test_刷卡寫入失敗_例外往外拋且不存訊息(rec):
    rec["upsert_error"] = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        process.handle(DB, _msg("store"), "ctbc")
    assert rec["events"] == []


def test_classify_送達時間換成台北時間naive():
    m, status, charge = process.classify(_msg("store"), "ctbc")
    assert m.sent_at == datetime(2026, 9, 5, 19, 43)
    assert m.sent_at.tzinfo is None
    assert (m.message_id, m.source, m.kind, m.content_type, status) == \
        ("900000000000000001", "ctbc", "spend", 22, "parsed")
    assert m.alt_text == "🔔LINE Pay聯名卡消費通知🔔"
    assert (charge.amount, charge.card_last4, charge.charge_time) == (1280, "1234", "19:42")


def test_classify_網路消費也拆得出來():
    _, status, charge = process.classify(_msg("online"), "ctbc")
    assert status == "parsed" and charge.amount == 359


def test_classify_台幣外幣金額也是non_twd():
    _, status, charge = process.classify(_msg("foreign_twd"), "ctbc")
    assert (status, charge) == ("non_twd", None)


def test_classify_message_id轉字串():
    msg = _msg("deposit")
    msg["id"] = 900000000000000005
    m, _, _ = process.classify(msg, "ctbc")
    assert m.message_id == "900000000000000005"


def test_PARSERS_中信用LINE通知parser():
    from cardrecon.parse import parse_ctbc_line
    assert process.PARSERS == {"ctbc": parse_ctbc_line}
