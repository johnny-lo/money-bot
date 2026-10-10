"""incidents.py：DB 外殼。重點是「感測器絕不能讓業務流程失敗」與 inbox 交接。"""
import json
from datetime import datetime

import pytest

from autofix import incidents
from models import AutofixIncident


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def with_for_update(self, *a, **k): return self
    def first(self): return self.rows[-1] if self.rows else None
    def all(self): return list(self.rows)


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added, self.deleted, self.committed = [], [], 0
    def query(self, *a, **k): return FakeQuery(self.rows)
    def add(self, r):
        r.id = r.id or 100 + len(self.added)
        self.added.append(r); self.rows.append(r)
    def delete(self, r): self.deleted.append(r)
    def flush(self): pass
    def commit(self): self.committed += 1
    def rollback(self): pass
    def close(self): pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOFIX_ENABLED", "1")
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))
    (tmp_path / "inbox").mkdir()
    monkeypatch.setattr(incidents, "now_tw", lambda: datetime(2026, 10, 10, 21, 0))
    return tmp_path


def _use(monkeypatch, s):
    monkeypatch.setattr(incidents, "SessionLocal", lambda: s)


def test_停用時完全不碰_DB(monkeypatch, env):
    monkeypatch.setenv("AUTOFIX_ENABLED", "")
    monkeypatch.setattr(incidents, "SessionLocal", lambda: (_ for _ in ()).throw(AssertionError))
    incidents.raise_incident("einvoice_login", "載具1", "t", {}, "2026-10-10")


def test_第一次命中建立_counting(monkeypatch, env):
    s = FakeSession(); _use(monkeypatch, s)
    incidents.raise_incident("einvoice_login", "載具1", "載具1 登入失敗", {"error": "e"}, "2026-10-10")
    assert s.added[0].status == "counting" and s.committed == 1
    assert list((env / "inbox").iterdir()) == []


def test_到門檻改_dispatched_並寫_inbox(monkeypatch, env):
    row = AutofixIncident(id=7, sensor="einvoice_login", signature="載具1", title="t",
                          status="counting", context={"urls": ["a"]},
                          hit_keys=[["2026-10-08", "x"], ["2026-10-09", "x"]])
    s = FakeSession([row]); _use(monkeypatch, s)
    incidents.raise_incident("einvoice_login", "載具1", "t", {"urls": ["b"]}, "2026-10-10")
    assert row.status == "dispatched"
    payload = json.loads((env / "inbox" / "7.json").read_text())
    assert payload["id"] == 7 and payload["context"]["urls"] == ["a", "b"]
    assert payload["escalated"] is False


def test_升級人工_建_needs_human_事件_也寫_inbox_給主機發卡(monkeypatch, env):
    row = AutofixIncident(id=3, sensor="einvoice_login", signature="載具1", title="t",
                          status="resolved", hit_keys=[], context={},
                          closed_at=datetime(2026, 10, 8))
    s = FakeSession([row]); _use(monkeypatch, s)
    incidents.raise_incident("einvoice_login", "載具1", "t", {}, "2026-10-10")
    new = s.added[0]
    assert new.status == "needs_human" and new.closed_at is not None
    payload = json.loads((env / "inbox" / f"{new.id}.json").read_text())
    assert payload["escalated"] is True


def test_DB_例外不外拋(monkeypatch, env, capsys):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(incidents, "SessionLocal", boom)
    incidents.raise_incident("einvoice_login", "載具1", "t", {}, "k")
    assert "autofix" in capsys.readouterr().out


def test_inbox_目錄不存在_只印_log_不建立(monkeypatch, env, capsys):
    (env / "inbox").rmdir()
    s = FakeSession(); _use(monkeypatch, s)
    incidents.raise_incident("drill", "drill", "演習", {}, "k")
    assert not (env / "inbox").exists()
    assert "inbox" in capsys.readouterr().out


def test_clear_只刪_counting(monkeypatch, env):
    a = AutofixIncident(id=1, sensor="scheduler_job", signature="j|E|f:g", title="t", status="counting")
    s = FakeSession([a]); _use(monkeypatch, s)
    incidents.clear("scheduler_job", "j|", prefix=True)
    assert s.deleted == [a]
    b = AutofixIncident(id=2, sensor="scheduler_job", signature="j|E|f:g", title="t", status="reported")
    s2 = FakeSession([b]); _use(monkeypatch, s2)
    incidents.clear("scheduler_job", "j|E|f:g")
    assert s2.deleted == []
