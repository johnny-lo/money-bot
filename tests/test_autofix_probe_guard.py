from pathlib import Path

import pytest

from autofix.probes import guard

PHONES = ["0912345678"]


def test_含手機號碼的非_GET_請求_算登入送出():
    assert guard.is_credential_submit("POST", "www.einvoice.nat.gov.tw",
                                      "mobile_phone=0912345678&password=x", PHONES)
    assert guard.is_credential_submit("POST", "www.einvoice.nat.gov.tw",
                                      '{"mobile":"0912345678"}', PHONES)


def test_GET_或別的網站或沒帶手機_不算():
    assert not guard.is_credential_submit("GET", "www.einvoice.nat.gov.tw", "0912345678", PHONES)
    assert not guard.is_credential_submit("POST", "evil.example", "0912345678", PHONES)
    assert not guard.is_credential_submit("POST", "www.einvoice.nat.gov.tw", "q=1", PHONES)


def test_預算_跨呼叫累計_第4次拒絕(tmp_path):
    p = tmp_path / "7.login_budget"
    assert [guard.take_budget(p) for _ in range(4)] == [True, True, True, False]
    assert guard.take_budget(p) is False


def test_mask_遮手機與_email():
    out = guard.mask("手機 0912345678 信箱 a.b@gmail.com", PHONES)
    assert "0912345678" not in out and "a.b@gmail.com" not in out


def test_網路層真的攔得住(tmp_path):
    pw = pytest.importorskip("playwright.async_api")
    import asyncio

    uninstall = guard.install(tmp_path / "b", PHONES, tmp_path / "dump")

    async def run():
        hits = []
        async with pw.async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context()   # 已被 guard patch → 自動掛攔截器
            async def backend(route, request):
                hits.append(request.method)
                await route.fulfill(body="ok")
            await ctx.route("https://www.einvoice.nat.gov.tw/login", backend)   # 後掛的 handler 也擋不掉 guard
            page = await ctx.new_page()
            for _ in range(4):
                await page.evaluate("""() => fetch('https://www.einvoice.nat.gov.tw/login',
                    {method:'POST', body:'mobile_phone=0912345678'}).catch(() => 'blocked')""")
            await browser.close()
        return hits

    try:
        assert asyncio.run(run()) == ["POST"] * 3
        assert list((tmp_path / "dump").glob("page*.txt"))   # close 前自動存頁面
    finally:
        uninstall()   # 還原 Playwright 類別，別汙染其他用 Playwright 的測試
