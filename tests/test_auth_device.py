import pytest
from fastapi import HTTPException

import auth


class FakeRec:
    def __init__(self, token, label=""):
        self.id = 1
        self.token = token
        self.label = label
        self.created_at = None
        self.last_used_at = None


class FakeQuery:
    def __init__(self, store):
        self._store = store

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._store.get("hit")


class FakeSession:
    def __init__(self, hit=None):
        self._store = {"hit": hit}
        self.added = []
        self.deleted = []
        self.committed = 0

    def query(self, *a, **k):
        return FakeQuery(self._store)

    def add(self, rec):
        self.added.append(rec)

    def delete(self, rec):
        self.deleted.append(rec)

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def refresh(self, rec):
        pass

    def close(self):
        pass


def _patch(monkeypatch, session):
    monkeypatch.setattr(auth, "SessionLocal", lambda: session)
    return session


def test_create_device_token_persists_and_returns_secret(monkeypatch):
    s = _patch(monkeypatch, FakeSession())
    t = auth.create_device_token(label="johnny-phone")
    assert isinstance(t, str) and len(t) >= 40   # token_urlsafe(32) ≈ 43 字元
    assert s.committed == 1
    assert s.added[0].token == t
    assert s.added[0].label == "johnny-phone"


def test_validate_device_token_hit_updates_last_used(monkeypatch):
    rec = FakeRec("dt-abc")
    s = _patch(monkeypatch, FakeSession(hit=rec))
    assert auth.validate_device_token("dt-abc") is True
    assert rec.last_used_at is not None
    assert s.committed == 1


def test_validate_device_token_miss(monkeypatch):
    _patch(monkeypatch, FakeSession(hit=None))
    assert auth.validate_device_token("nope") is False


def test_validate_device_token_empty_skips_db(monkeypatch):
    # 空值不應該打 DB（也不應該炸）
    monkeypatch.setattr(auth, "SessionLocal",
                        lambda: pytest.fail("空 token 不該開 session"))
    assert auth.validate_device_token("") is False
    assert auth.validate_device_token(None) is False


def test_revoke_device_token(monkeypatch):
    rec = FakeRec("dt-abc")
    s = _patch(monkeypatch, FakeSession(hit=rec))
    assert auth.revoke_device_token("dt-abc") is True
    assert s.deleted == [rec]


def test_revoke_device_token_miss(monkeypatch):
    _patch(monkeypatch, FakeSession(hit=None))
    assert auth.revoke_device_token("nope") is False


def test_require_token_accepts_short_token(monkeypatch):
    monkeypatch.setattr(auth, "validate_report_token", lambda t: "user1" if t == "short-ok" else None)
    auth.require_token(token="short-ok", x_device_token=None)  # 不丟例外即通過


def test_require_token_accepts_device_token_header(monkeypatch):
    monkeypatch.setattr(auth, "validate_device_token", lambda t: t == "dt-ok")
    auth.require_token(token=None, x_device_token="dt-ok")


def test_require_token_rejects_when_both_invalid(monkeypatch):
    monkeypatch.setattr(auth, "validate_report_token", lambda t: None)
    monkeypatch.setattr(auth, "validate_device_token", lambda t: False)
    with pytest.raises(HTTPException) as e:
        auth.require_token(token="bad", x_device_token="bad")
    assert e.value.status_code == 401


def test_require_token_rejects_when_nothing_given(monkeypatch):
    with pytest.raises(HTTPException) as e:
        auth.require_token(token=None, x_device_token=None)
    assert e.value.status_code == 401
