"""PWA →報表頁的入口：短效 token 換發，以及「不能自我繁殖」那道不變式。

兩層認證的守衛是：只有短效 token 能換長效裝置 token（routes/device.py），
所以洩漏的裝置 token 無法自我繁殖。PWA 會用裝置 token 去鑄短效 token 開報表頁，
若不加限制就形成 device → short → device 的環，那道守衛就白寫了。
解法是短效 token 帶 can_mint_device 旗標，PWA 鑄的那顆是 False。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
import routes.device as device_route
import routes.report as report_route


@pytest.fixture(autouse=True)
def clean_store():
    auth._token_store.clear()
    yield
    auth._token_store.clear()


# ── auth 層：旗標本身 ──────────────────────────────────────────

def test_discord_line_token_can_mint_device():
    # LINE/Discord 發的連結是「剛從對話拿到」的邀請函，維持可換發
    t = auth.generate_report_token("user1")
    assert auth.validate_report_token(t) == "user1"
    assert auth.report_token_can_mint_device(t) is True


def test_pwa_token_cannot_mint_device():
    t = auth.generate_report_token("pwa", can_mint_device=False)
    assert auth.validate_report_token(t) == "pwa"   # 看報表可以
    assert auth.report_token_can_mint_device(t) is False   # 換發長效不行


def test_unknown_token_cannot_mint():
    assert auth.report_token_can_mint_device("nope") is False
    assert auth.report_token_can_mint_device("") is False
    assert auth.report_token_can_mint_device(None) is False


def test_expired_token_cannot_mint():
    from datetime import datetime, timedelta
    t = auth.generate_report_token("user1")
    auth._token_store[t]["expires_at"] = datetime.now() - timedelta(seconds=1)
    assert auth.report_token_can_mint_device(t) is False


# ── device route：換發前的守衛 ────────────────────────────────

@pytest.fixture
def device_client(monkeypatch):
    monkeypatch.setattr(device_route, "create_device_token", lambda label="": "dt-new")
    app = FastAPI()
    app.include_router(device_route.router)
    return TestClient(app)


def test_device_token_issued_for_invite_token(device_client):
    t = auth.generate_report_token("user1")
    r = device_client.post(f"/api/device-token?token={t}")
    assert r.status_code == 200
    assert r.json()["token"] == "dt-new"


def test_device_token_refused_for_pwa_minted_token(device_client):
    """環的封口：裝置 token 鑄出來的短效 token 換不回裝置 token。"""
    t = auth.generate_report_token("pwa", can_mint_device=False)
    r = device_client.post(f"/api/device-token?token={t}")
    assert r.status_code == 403


def test_device_token_refused_for_garbage(device_client):
    assert device_client.post("/api/device-token?token=nope").status_code == 401


# ── report route：PWA 用的鑄幣口 ──────────────────────────────

@pytest.fixture
def report_client():
    app = FastAPI()
    app.include_router(report_route.router)
    app.dependency_overrides[auth.require_token] = lambda: None
    return TestClient(app)


def test_report_token_endpoint_mints_a_short_token(report_client):
    r = report_client.post("/api/report-token")
    assert r.status_code == 200
    t = r.json()["token"]
    assert auth.validate_report_token(t) == "pwa"


def test_report_token_endpoint_output_cannot_mint_device(report_client):
    t = report_client.post("/api/report-token").json()["token"]
    assert auth.report_token_can_mint_device(t) is False


def test_ledger_filter_js_is_served_as_module(report_client):
    """報表頁與 PWA 共用同一份純函式檔——兩份必漂移。"""
    r = report_client.get("/report/ledger_filter.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "export function applyFilters" in r.text
