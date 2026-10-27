import json
from datetime import datetime

import pytest

import codex_cli
from lineinbox import watchdog
from lineinbox.fallback import SCHEMA
from lineinbox.types import CODEX_PARSED, UNREADABLE, InboxMessage, ListenerState


NOW = datetime(2026, 10, 27, 12, 0)


@pytest.fixture(autouse=True)
def _禁止呼叫真的codex(monkeypatch):
    """watchdog 測試必須攔住底層程序，即使上層 monkeypatch 失效也不能出網。"""
    calls = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("測試不得呼叫真的 codex")

    monkeypatch.setattr(codex_cli, "_codex_exec", boom)
    yield
    assert calls == []


def _message(message_id="900000000000000001"):
    return InboxMessage(
        message_id=message_id,
        source="ctbc",
        sent_at=NOW,
        alt_text="合成消費通知",
        content_type=22,
        texts=["刷卡通知", "NT$1280", "卡末四碼：", "1234"],
        kind="spend",
    )


def _wire(monkeypatch, items):
    calls = {"status": [], "upsert": [], "unreadable": [], "listener": [], "alerted": []}
    monkeypatch.setattr(watchdog.line_repo, "pending_codex", lambda db, limit: list(items))
    monkeypatch.setattr(watchdog.line_repo, "set_status",
                        lambda db, mid, status, error=None: calls["status"].append((mid, status, error)))
    monkeypatch.setattr(watchdog.line_repo, "listener_state", lambda db: None)
    monkeypatch.setattr(watchdog.line_repo, "mark_alerted",
                        lambda db, kind: calls["alerted"].append(kind))
    monkeypatch.setattr(watchdog.card_repo, "upsert_charges",
                        lambda db, mid, charges: calls["upsert"].append((mid, charges)) or 1)
    monkeypatch.setattr(watchdog.lineinbox_ui, "notify_unreadable",
                        lambda unreadable: calls["unreadable"].append(list(unreadable)))
    monkeypatch.setattr(watchdog.lineinbox_ui, "notify_listener",
                        lambda kind, state: calls["listener"].append((kind, state)))
    return calls


def test_codex成功後寫刷卡並更新狀態(monkeypatch):
    item = _message()
    calls = _wire(monkeypatch, [item])
    codex_calls = []

    def fake_codex(prompt, model=None, schema=None):
        codex_calls.append((prompt, model, schema))
        return json.dumps({
            "amount": 1280,
            "card_last4": "1234",
            "date": "2026-10-27",
            "time": "11:58",
            "merchant": "XX 測試店",
            "foreign": False,
        })

    monkeypatch.setattr(codex_cli, "codex_text", fake_codex)

    result = watchdog.run(now=NOW, db=object())

    assert result == {"codex": 1, "unreadable": 0, "alert": None}
    assert len(codex_calls) == 1
    assert codex_calls[0][1:] == ("gpt-5.6-sol", SCHEMA)
    assert calls["upsert"][0][0] == "line:900000000000000001"
    assert calls["upsert"][0][1][0].amount == 1280
    assert calls["status"] == [(item.message_id, CODEX_PARSED, None)]
    assert calls["unreadable"] == []


@pytest.mark.parametrize("failure", ["壞 JSON", RuntimeError("合成失敗")])
def test_codex回覆無效或丟例外會標成看不懂並通知(monkeypatch, failure):
    item = _message()
    calls = _wire(monkeypatch, [item])

    def fake_codex(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(codex_cli, "codex_text", fake_codex)

    result = watchdog.run(now=NOW, db=object())

    assert result == {"codex": 0, "unreadable": 1, "alert": None}
    assert calls["upsert"] == []
    assert len(calls["status"]) == 1
    assert calls["status"][0][0:2] == (item.message_id, UNREADABLE)
    assert calls["status"][0][2]
    assert calls["unreadable"] == [[item]]


@pytest.mark.parametrize("alerted,expected_notifications", [(None, 1), ("kicked", 0)])
def test_listener被登出只在告警種類改變時通知(monkeypatch, alerted, expected_notifications):
    calls = _wire(monkeypatch, [])
    state = ListenerState("kicked", NOW, "登入失效", alerted)
    monkeypatch.setattr(watchdog.line_repo, "listener_state", lambda db: state)

    result = watchdog.run(now=NOW, db=object())

    assert result == {"codex": 0, "unreadable": 0, "alert": "kicked"}
    assert len(calls["listener"]) == expected_notifications
    assert calls["alerted"] == (["kicked"] if expected_notifications else [])
