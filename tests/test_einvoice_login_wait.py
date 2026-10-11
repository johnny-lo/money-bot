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


class _FakeLocator:
    def __init__(self, page):
        self.page = page

    async def inner_text(self):
        self.page.reads += 1
        if self.page.reads in self.page.fail_reads or self.page.reads > self.page.ok_reads:
            raise RuntimeError("body 讀取失敗")
        return self.page.body


class _FakePage:
    def __init__(self, url, body, ok_reads=1, fail_reads=()):
        self.url = url
        self.body = body
        self.ok_reads = ok_reads
        self.fail_reads = set(fail_reads)
        self.reads = 0

    def locator(self, _sel):
        return _FakeLocator(self)

    async def fill(self, *_a):
        pass

    async def click(self, *_a):
        pass

    async def wait_for_timeout(self, _ms):
        pass

    async def wait_for_load_state(self, *_a, **_k):
        pass


def test_非portal_btc網址沿用先前讀到的body不重讀(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    async def _captcha(_page):
        return "1234", b""

    monkeypatch.setattr(einvoice, "_enter_login_flow", _noop)
    monkeypatch.setattr(einvoice, "_solve_captcha", _captcha)
    monkeypatch.setattr(einvoice, "_detect_error", _noop)
    monkeypatch.setattr(einvoice.captcha_ocr, "save_sample", lambda *_a, **_k: None)
    # 只有第一次讀得到(含查詢關鍵字)，之後讀取一律例外
    page = _FakePage(OTHER_URL, "查詢發票", ok_reads=1)
    ok, _ = asyncio.run(einvoice._login_attempt(page, "0900", "pw", 1))
    assert ok is True
    assert page.reads == 1


def test_永遠畫不出來真的讀滿tries次():
    page = _FakePage(SEARCH_URL, "載入中", ok_reads=99)
    landing, _ = asyncio.run(einvoice._wait_landing(page, SEARCH_URL, tries=4, interval_ms=1))
    assert landing == "unknown"
    assert page.reads == 4
