from datetime import datetime, timedelta

from lineinbox.health import alert_kind, should_send
from lineinbox.types import ListenerState


NOW = datetime(2026, 10, 27, 12, 0)


def _state(state="ok", heartbeat_at=NOW, alerted=None):
    return ListenerState(state, heartbeat_at, None, alerted)


def test_沒有狀態就不告警():
    assert alert_kind(None, NOW, 60) is None


def test_被登出優先於心跳新舊():
    assert alert_kind(_state("kicked", NOW), NOW, 60) == "kicked"


def test_沒有心跳或超過期限視為停擺():
    assert alert_kind(_state(heartbeat_at=None), NOW, 60) == "stale"
    assert alert_kind(_state(heartbeat_at=NOW - timedelta(minutes=61)), NOW, 60) == "stale"


def test_正常且期限內不告警():
    assert alert_kind(_state(heartbeat_at=NOW - timedelta(minutes=60)), NOW, 60) is None


def test_同種告警不重發_換種才發():
    assert should_send("kicked", "kicked") is False
    assert should_send("stale", "kicked") is True
    assert should_send(None, "kicked") is False
