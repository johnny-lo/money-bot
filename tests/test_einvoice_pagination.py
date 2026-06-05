"""einvoice 翻頁選擇器的回歸測試(hermetic,不連網)。

守住的 bug:政府站分頁是 Bootstrap `<a class="page-link">下一頁</a>`,舊版用
button[aria-label="下一頁"]/a[rel=next] 從來沒中過 → 多頁查詢只抓得到第 1 頁。
也守「最後一頁(li.disabled)時要回 False」讓翻頁迴圈正確結束。

需要 Playwright(僅容器內有);主機無則整檔 skip。
"""
import asyncio
import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402
import einvoice  # noqa: E402

FIXTURE = """<!doctype html><html><body>
<ul class="pagination">
  <li class="page-item active"><a class="page-link">1</a></li>
  <li class="page-item"><a class="page-link">2</a></li>
  <li class="page-item" id="nextli">
    <a class="page-link" onclick="window.__clicked=true">下一頁<span class="visually-hidden">下一頁</span></a>
  </li>
</ul></body></html>"""


async def _probe(html):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await (await b.new_context()).new_page()
        await page.set_content(html)
        try:
            found = await page.evaluate(einvoice._NEXT_PAGE_FIND)
            clicked = None
            if found:
                await page.evaluate(einvoice._NEXT_PAGE_CLICK)
                clicked = await page.evaluate("() => !!window.__clicked")
            return found, clicked
        finally:
            await b.close()


def test_next_page_found_and_clicked_when_enabled():
    found, clicked = asyncio.run(_probe(FIXTURE))
    assert found is True       # 舊 selector 在這裡會是 False(就是 bug)
    assert clicked is True


def test_next_page_not_found_when_disabled():
    last = FIXTURE.replace('class="page-item" id="nextli"', 'class="page-item disabled" id="nextli"')
    found, _ = asyncio.run(_probe(last))
    assert found is False       # 最後一頁 → 翻頁迴圈必須停


async def _active(html):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await (await b.new_context()).new_page()
        await page.set_content(html)
        try:
            return await page.evaluate(einvoice._ACTIVE_PAGE_JS)
        finally:
            await b.close()


def test_active_page_reads_current_page_number():
    # 最後一頁偵測靠「點下一頁後 active 頁碼有沒有變」,所以這個 selector 要準
    html = ('<ul class="pagination">'
            '<li class="page-item"><a class="page-link">1</a></li>'
            '<li class="page-item active"><a class="page-link">2</a></li></ul>')
    assert asyncio.run(_active(html)) == "2"
