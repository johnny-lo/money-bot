"""_wait_landing 回歸測試(hermetic,不連網)。

守住的 bug:登入其實成功、已落在 /portal/btc/ 頁，但 SPA 還沒畫完(body 沒有「登出」
也沒有查詢關鍵字)，舊邏輯只讀一次就判 unknown → 多燒一次登入。
需要 Playwright(僅容器內有);主機無則整檔 skip。
"""
import asyncio
import time
import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402
import einvoice  # noqa: E402

SEARCH_URL = "https://example.invalid/portal/btc/mobile/btc502w/search"
OTHER_URL = "https://example.invalid/somewhere/else"

LATE_HTML = """<!doctype html><html><body>載入中
<script>setTimeout(() => { document.body.innerText = '登出 查詢發票'; }, 1500);</script>
</body></html>"""

NEVER_HTML = "<!doctype html><html><body>載入中</body></html>"


async def _run(html, fn):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        try:
            return await fn(page)
        finally:
            await browser.close()


def test_慢畫完的落地頁輪詢後判成search():
    async def go(page):
        immediate = einvoice._login_landing(
            SEARCH_URL, await page.locator("body").inner_text())
        got = await einvoice._wait_landing(page, SEARCH_URL, tries=20, interval_ms=200)
        return immediate, got

    immediate, (landing, body) = asyncio.run(_run(LATE_HTML, go))
    assert immediate == "unknown"
    assert landing == "search"
    assert "查詢發票" in body


def test_非portal_btc網址只讀一次():
    async def go(page):
        t = time.monotonic()
        got = await einvoice._wait_landing(page, OTHER_URL, tries=20, interval_ms=1000)
        return got, time.monotonic() - t

    (landing, _), elapsed = asyncio.run(_run(LATE_HTML, go))
    assert landing == "unknown"
    assert elapsed < 1.0


def test_永遠畫不出來用完次數回unknown():
    async def go(page):
        return await einvoice._wait_landing(page, SEARCH_URL, tries=3, interval_ms=100)

    landing, body = asyncio.run(_run(NEVER_HTML, go))
    assert landing == "unknown"
    assert "載入中" in body
