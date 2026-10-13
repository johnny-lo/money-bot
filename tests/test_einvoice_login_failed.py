"""登入全敗必須「看得見」：拋 LoginFailed，補拓記失敗、高水位不推進。

背景：若 _scrape_carrier 在登入失敗時 `return []` → 呼叫端看到「抓 0 張」
當成功 → 高水位照推，那幾天的發票永久漏抓，而且自動修復的感測器數不到失敗。
"""
import asyncio
from datetime import date

import pytest

import einvoice
import invoice_backfill


def test_login_全敗拋_LoginFailed_並帶每次嘗試摘要(monkeypatch):
    async def fake_attempt(page, phone, password, attempt):
        return None, f"第{attempt}次：未知狀態 URL=https://x/btc508w"
    monkeypatch.setattr(einvoice, "_login_attempt", fake_attempt)
    with pytest.raises(einvoice.LoginFailed) as ei:
        asyncio.run(einvoice._login(object(), "0912345678", "pw"))
    assert len(ei.value.attempts) == einvoice.MAX_CAPTCHA_RETRIES
    assert "btc508w" in str(ei.value)


def test_login_單次嘗試拋例外也只算一次失敗_繼續重試(monkeypatch):
    calls = []
    async def fake_attempt(page, phone, password, attempt):
        calls.append(attempt)
        if attempt == 1:
            raise TimeoutError("等不到登入頁")
        return True, "ok"
    monkeypatch.setattr(einvoice, "_login_attempt", fake_attempt)
    assert asyncio.run(einvoice._login(object(), "0912345678", "pw")) is True
    assert calls == [1, 2]


def test_login_帳密錯誤立即停止不再重試(monkeypatch):
    calls = []
    async def fake_attempt(page, phone, password, attempt):
        calls.append(attempt)
        return False, "帳號或密碼錯誤"
    monkeypatch.setattr(einvoice, "_login_attempt", fake_attempt)
    with pytest.raises(einvoice.LoginFailed):
        asyncio.run(einvoice._login(object(), "0912345678", "pw"))
    assert calls == [1]


def test_補拓遇到_LoginFailed_記失敗且高水位不推進(monkeypatch):
    monkeypatch.setattr(invoice_backfill, "get_last_covered", lambda: date(2026, 10, 1))
    advanced = []
    monkeypatch.setattr(invoice_backfill, "set_last_covered", advanced.append)
    monkeypatch.setattr(invoice_backfill, "_list_carriers", lambda: [(1, "0912345678", "pw")])
    def boom(*a, **k):
        raise einvoice.LoginFailed(["第1次：未知狀態"])
    monkeypatch.setattr(invoice_backfill, "_scrape_one", boom)
    r = invoice_backfill.sync_with_backfill(today=date(2026, 10, 3))
    assert r["ok"] is False
    assert advanced == []
    assert r["failures"][0]["error"].startswith("LoginFailed")
