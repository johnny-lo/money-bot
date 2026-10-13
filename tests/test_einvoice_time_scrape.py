"""發票開立時間的爬蟲端（hermetic Playwright，所有網路都被 page.route 攔下，不出網）。

照 tests/test_einvoice_detail.py 的做法：點號碼開明細 modal 時，假網頁打 getCarrierInvoiceData，
回應由測試假造。需要 Playwright（僅容器內有）；主機無則整檔 skip。
"""
import asyncio
from datetime import time

import pytest

pw = pytest.importorskip("playwright.async_api")
import einvoice  # noqa: E402

BASE = "https://einvoice.test"
FIXTURE_HTML = r"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<table border="1">
  <tr><th>序</th><th>條碼</th><th>發票號碼</th><th>發票金額</th><th>發票日期</th></tr>
  <tr><td></td><td>手機條碼</td>
      <td>手機條碼<a href="javascript:void(0)" onclick="openModal('AA00000001')">AA00000001</a></td>
      <td>55</td><td>2026年6月5日</td></tr>
  <tr><td></td><td></td><td>某某商店股份有限公司</td></tr>
  <tr><td></td><td>手機條碼</td>
      <td>手機條碼<a href="javascript:void(0)" onclick="openModal('BB00000002')">BB00000002</a></td>
      <td>43</td><td>2026年6月4日</td></tr>
  <tr><td></td><td></td><td>某某便利商店股份有限公司</td></tr>
  <tr><td></td><td>手機條碼</td>
      <td>手機條碼<a href="javascript:void(0)" onclick="openModal('CC00000003')">CC00000003</a></td>
      <td>20</td><td>2026年6月3日</td></tr>
  <tr><td></td><td></td><td>某某飲料店</td></tr>
</table>
<script>
const DATA = {
  'AA00000001': [['大-冰拿鐵','1','55','55']],
  'BB00000002': [['禦飯糰','1','30','30'], ['茶葉蛋','1','13','13']],
  'CC00000003': [['紅茶','1','20','20']],
};
function openModal(no){
  // 跟真站一樣：點明細時打 getCarrierInvoiceData（測試用 page.route 假造回應）
  fetch('/btc/api/btc502w/getCarrierInvoiceData?no=' + no, {method: 'POST'}).catch(() => {});
  const m = document.createElement('div');
  m.className = 'modal fade modal_barcode_detail show';
  const rows = DATA[no].map(r =>
    `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`).join('');
  m.innerHTML =
    `<a class="close_btn" data-bs-dismiss="modal" href="javascript:void(0)" onclick="closeModal()">關閉</a>`
    + `<table><tr><th>品名</th><th>數量</th><th>單價</th><th>金額</th></tr>${rows}</table>`;
  document.body.appendChild(m);
}
function closeModal(){ document.querySelectorAll('.modal_barcode_detail.show').forEach(e => e.remove()); }
</script>
</body></html>"""


async def _scrape(api):
    """api(no) → None＝中斷連線（沒有回應）；str＝回應 body。所有網路都被 route 攔下，不出網。"""
    async with pw.async_playwright() as p:
        browser = await p.chromium.launch()
        page = await (await browser.new_context()).new_page()

        async def handle(route):
            url = route.request.url
            if url.endswith("/list.html"):
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=FIXTURE_HTML)
            elif "getCarrierInvoiceData" in url:
                body = api(url.rsplit("=", 1)[1])
                if body is None:
                    await route.abort()
                else:
                    await route.fulfill(status=200, content_type="application/json", body=body)
            else:
                await route.abort()
        await page.route("**/*", handle)
        await page.goto(f"{BASE}/list.html")
        try:
            return await einvoice._parse_current_page(page, since_date="2026-01-01")
        finally:
            await browser.close()


def test_爬蟲_有回應拿到時間_沒回應或壞JSON是None_品項照抓():
    bodies = {
        "AA00000001": '{"invoiceNumber": "AA00000001", "invoiceTime": "12:38:00"}',
        "BB00000002": None,                                   # 沒有回應
        "CC00000003": "{not json",                            # JSON 壞掉
    }
    invoices, stop = asyncio.run(_scrape(bodies.get))
    by_no = {inv["invoice_no"]: inv for inv in invoices}
    assert stop is False and set(by_no) == set(bodies)
    assert by_no["AA00000001"]["time"] == time(12, 38)
    assert by_no["BB00000002"]["time"] is None
    assert by_no["CC00000003"]["time"] is None
    assert [it["name"] for it in by_no["AA00000001"]["items"]] == ["大-冰拿鐵"]
    assert [it["name"] for it in by_no["BB00000002"]["items"]] == ["禦飯糰", "茶葉蛋"]
    assert [it["name"] for it in by_no["CC00000003"]["items"]] == ["紅茶"]


def test_爬蟲_invoiceTime包在巢狀資料裡也找得到_格式不對是None():
    bodies = {
        "AA00000001": '{"code": 200, "data": {"invoiceTime": "08:05:09"}}',
        "BB00000002": '{"invoiceTime": "25:00:00"}',
        "CC00000003": '{"msg": "沒有這個欄位"}',
    }
    invoices, _ = asyncio.run(_scrape(bodies.get))
    by_no = {inv["invoice_no"]: inv for inv in invoices}
    assert by_no["AA00000001"]["time"] == time(8, 5, 9)
    assert by_no["BB00000002"]["time"] is None and by_no["CC00000003"]["time"] is None
    assert [it["name"] for it in by_no["BB00000002"]["items"]] == ["禦飯糰", "茶葉蛋"]
