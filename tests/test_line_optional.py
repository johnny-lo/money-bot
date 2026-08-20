"""LINE 憑證是可選的：缺設定時整個停用，而不是在 import 期炸掉全站。

背景：舊寫法 `LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))` 在 token 為 None 時
會 TypeError（SDK 把 token 直接串進 Authorization header）→ **import 崩潰 = 全站掛**，
webhook、Discord Bot、PWA 一起沒。Discord 早就有 `if discord_token:` 守著，這裡補齊。
"""
import importlib

import pytest
from fastapi import FastAPI

import line_handler


@pytest.fixture(autouse=True)
def _restore_module():
    """測完把模組重載回真實環境，避免污染同一輪的其他測試。"""
    yield
    importlib.reload(line_handler)


def _reload_without_line(monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    return importlib.reload(line_handler)


def test_缺憑證時_import_不崩潰(monkeypatch):
    """這行在舊版會直接 TypeError。"""
    m = _reload_without_line(monkeypatch)
    assert m.LINE_ENABLED is False
    assert m.line_bot_api is None
    assert m.handler is None


def test_缺憑證時不掛載_callback_路由(monkeypatch):
    m = _reload_without_line(monkeypatch)
    app = FastAPI()
    m.register_line_routes(app)
    assert "/callback" not in [r.path for r in app.routes]


def test_只有一半憑證也算停用(monkeypatch):
    """只設 token 沒設 secret 時，WebhookHandler(None) 一樣會出事，所以要兩個都有才啟用。"""
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "dummy-token")
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    m = importlib.reload(line_handler)
    assert m.LINE_ENABLED is False


def test_有完整憑證時照常掛載(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "dummy-token")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "dummy-secret")
    m = importlib.reload(line_handler)
    assert m.LINE_ENABLED is True
    app = FastAPI()
    m.register_line_routes(app)
    assert "/callback" in [r.path for r in app.routes]


def test_沒帶簽章的_callback_回400而不是500(monkeypatch):
    """公開網址上任何人都能戳 /callback。沒帶簽章時 SDK 會對 None 做 .encode()
    → AttributeError → 500 + traceback。擋在前面，讓它是一個乾淨的壞請求。"""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "dummy-token")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "dummy-secret")
    m = importlib.reload(line_handler)
    app = FastAPI()
    m.register_line_routes(app)
    res = TestClient(app, raise_server_exceptions=False).post("/callback", json={"events": []})
    assert res.status_code == 400


def test_簽章錯誤的_callback_也是400(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "dummy-token")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "dummy-secret")
    m = importlib.reload(line_handler)
    app = FastAPI()
    m.register_line_routes(app)
    res = TestClient(app, raise_server_exceptions=False).post(
        "/callback", json={"events": []}, headers={"X-Line-Signature": "bogus"})
    assert res.status_code == 400
