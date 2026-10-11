"""呼叫點真的從 secrets 檔讀（不是只換了名字）。全部不出網：網路呼叫一律 monkeypatch。"""
import asyncio
import importlib
import json

import pytest


def _secrets(tmp_path, monkeypatch, files: dict[str, str]):
    d = tmp_path / "secrets"
    d.mkdir()
    for name, value in files.items():
        (d / name).write_text(value, encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(d))


def test_list_carriers_reads_secret_files(tmp_path, monkeypatch):
    import einvoice
    for k in ("EINVOICE_PHONE_1", "EINVOICE_PASSWORD_1", "EINVOICE_PHONE_2", "EINVOICE_PASSWORD_2"):
        monkeypatch.delenv(k, raising=False)
    _secrets(tmp_path, monkeypatch, {
        "einvoice_phone_1": "0911000001\n", "einvoice_password_1": "pw1",
        "einvoice_phone_2": "", "einvoice_password_2": "",   # 選填：空佔位
    })
    assert einvoice._list_carriers() == [(1, "0911000001", "pw1")]


def test_line_enabled_from_secret_files(tmp_path, monkeypatch):
    import line_handler
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    _secrets(tmp_path, monkeypatch, {"line_channel_access_token": "tok", "line_channel_secret": "sec"})
    try:
        assert importlib.reload(line_handler).LINE_ENABLED is True
    finally:
        # 重載回「沒有機密」的測試環境，別讓 tok/sec 留在模組狀態污染其他測試
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("SECRETS_DIR", str(empty))
        importlib.reload(line_handler)


def test_gemini_text_uses_key_from_file(tmp_path, monkeypatch):
    import gemini
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _secrets(tmp_path, monkeypatch, {"gemini_api_key": "FILEKEY"})
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}).encode()

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(gemini.urllib.request, "urlopen", fake_urlopen)
    assert gemini.gemini_text("hi", model="m") == "ok"
    assert "key=FILEKEY" in seen["url"]


def test_places_search_uses_key_from_file(tmp_path, monkeypatch):
    from food import places
    monkeypatch.delenv("GOOGLE_PLACES_SERVER_KEY", raising=False)
    _secrets(tmp_path, monkeypatch, {"google_places_server_key": "PKEY"})
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"places": []}).encode()

    def fake_urlopen(req, timeout=None):
        seen["key"] = req.get_header("X-goog-api-key")
        return _Resp()

    monkeypatch.setattr(places.urllib.request, "urlopen", fake_urlopen)
    assert places.search_text("鼎泰豐") is None
    assert seen["key"] == "PKEY"


def test_verify_scrape_reads_secret_files(tmp_path, monkeypatch):
    import einvoice
    from autofix import verify
    _secrets(tmp_path, monkeypatch, {"einvoice_phone_1": "0911000001", "einvoice_password_1": "pw1"})
    got = {}

    async def fake_scrape(phone, pw, days):
        got["args"] = (phone, pw, days)
        return [object(), object()]

    monkeypatch.setattr(einvoice, "_scrape_carrier", fake_scrape)
    assert verify._scrape(1) == 2
    assert got["args"] == ("0911000001", "pw1", 1)


def test_verify_scrape_missing_secret_raises(tmp_path, monkeypatch):
    from autofix import verify
    monkeypatch.delenv("EINVOICE_PHONE_1", raising=False)
    monkeypatch.delenv("EINVOICE_PASSWORD_1", raising=False)
    _secrets(tmp_path, monkeypatch, {"einvoice_phone_1": "", "einvoice_password_1": ""})
    with pytest.raises(KeyError):
        verify._scrape(1)
