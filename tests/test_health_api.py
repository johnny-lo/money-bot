"""/healthz 端點測試：engine 全 monkeypatch，不碰真 DB。

重點不只是「回 200」，而是**回應不能洩漏任何內部資訊**——這支端點免 token、
等於公開，DB 例外訊息裡就有帳密與主機名，漏出去就是送分。
"""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.health as health


# 假的 DB 例外訊息：故意塞滿「絕對不可以出現在 HTTP 回應裡」的東西
LEAKY = (
    "(psycopg2.OperationalError) connection to server at \"db\" (172.18.0.2), port 5432 failed: "
    "FATAL: password authentication failed for user \"user\"\n"
    "[SQL: SELECT 1] (Background on this error at: https://sqlalche.me/e/20/e3q8)\n"
    "DATABASE_URL=postgresql://user:password@db:5432/money_db  /app/database.py"
)


class _FakeEngine:
    """connect() 依 ok 決定成功或拋例外；成功時當成 context manager 用。"""

    def __init__(self, ok=True, error=None):
        self.ok = ok
        self.error = error
        self.queries = []

    @contextmanager
    def connect(self):
        if not self.ok:
            raise RuntimeError(self.error)
        engine = self

        class _Conn:
            def execute(self, stmt):
                engine.queries.append(str(stmt))
                return None

        yield _Conn()


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(health.router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── 正常路徑 ─────────────────────────────────────────────────

def test_healthz_ok(client, monkeypatch):
    fake = _FakeEngine(ok=True)
    monkeypatch.setattr(health, "engine", fake)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}          # 只有 status，沒有夾帶
    assert fake.queries == ["SELECT 1"]          # 真的有戳 DB，不是純 app liveness


def test_healthz_needs_no_token(client, monkeypatch):
    """免 token：不帶 query token、不帶 X-Device-Token 也要 200（不能回 401）。"""
    monkeypatch.setattr(health, "engine", _FakeEngine(ok=True))
    assert client.get("/healthz").status_code == 200


def test_healthz_no_store(client, monkeypatch):
    """健康檢查拿到快取的舊答案＝謊報健康，一定要 no-store。"""
    monkeypatch.setattr(health, "engine", _FakeEngine(ok=True))
    assert client.get("/healthz").headers["cache-control"] == "no-store"


# ── DB 不通 ──────────────────────────────────────────────────

def test_healthz_db_down_503(client, monkeypatch):
    monkeypatch.setattr(health, "engine", _FakeEngine(ok=False, error=LEAKY))
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable"}


# ── 不洩漏內部資訊（這支端點是公開的）─────────────────────────

@pytest.mark.parametrize("ok", [True, False])
def test_healthz_never_leaks_internals(client, monkeypatch, ok):
    monkeypatch.setattr(health, "engine", _FakeEngine(ok=ok, error=LEAKY))
    r = client.get("/healthz")
    body = r.text
    for secret in ("password", "postgresql://", "psycopg2", "5432", "172.18",
                   "/app", "database.py", "SELECT 1", "sqlalche.me", "money_db", "user"):
        assert secret not in body, f"回應洩漏了「{secret}」：{body}"
    # 回應只有一個 key，未來加欄位會在這裡先被擋下來
    assert list(r.json().keys()) == ["status"]
    # header 也不能夾帶（server/版本之類）
    assert not any(h.lower().startswith(("x-", "server-version")) for h in r.headers)


def test_healthz_db_error_goes_to_log_not_response(client, monkeypatch, capsys):
    """細節要進伺服器 log（給人排查），但不能進回應。"""
    monkeypatch.setattr(health, "engine", _FakeEngine(ok=False, error=LEAKY))
    r = client.get("/healthz")
    assert "password" not in r.text
    assert "password" in capsys.readouterr().out      # log 有，才查得出根因
