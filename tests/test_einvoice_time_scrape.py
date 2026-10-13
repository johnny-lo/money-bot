"""發票開立時間的爬蟲端（hermetic Playwright，所有網路都被 page.route 攔下，不出網）。

照 tests/test_einvoice_detail.py 的做法，假網頁模仿真站：載入時打清單 API searchCarrierInvoice
（回 content[] 的 invoiceNumber＋token），點號碼開明細 modal 時打 getCarrierInvoiceData
（POST body 帶該張的 token；回應沒有發票號碼，只有 invoiceDate／invoiceTime／totalAmount）。
回應由測試假造。需要 Playwright（僅容器內有）；主機無則整檔 skip。
"""
import asyncio
import json
from datetime import time

import pytest

pw = pytest.importorskip("playwright.async_api")
import einvoice  # noqa: E402

BASE = "https://einvoice.test"
TOKENS = {"AA00000001": "tokAAAA1111", "BB00000002": "tokBBBB2222", "CC00000003": "tokCCCC3333"}
NO_BY_TOKEN = {v: k for k, v in TOKENS.items()}
LIST_ROWS = {"AA00000001": ("20260605", "55"), "BB00000002": ("20260604", "43"),
             "CC00000003": ("20260603", "20")}
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
const TOKENS = __TOKENS__;
const DATA = {
  'AA00000001': [['大-冰拿鐵','1','55','55']],
  'BB00000002': [['禦飯糰','1','30','30'], ['茶葉蛋','1','13','13']],
  'CC00000003': [['紅茶','1','20','20']],
};
// 跟真站一樣：清單是 searchCarrierInvoice 的 JSON（每筆有 invoiceNumber 與 token）
fetch('/btc/api/btc502w/searchCarrierInvoice', {method: 'POST', body: '{"page":0}'}).catch(() => {});
function openModal(no){
  // 點明細時打 getCarrierInvoiceData，POST body 帶這張的 token
  fetch('/btc/api/btc502w/getCarrierInvoiceData', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: TOKENS[no], carrierId2: 'xxxx', searchType: 1})}).catch(() => {});
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
</body></html>""".replace("__TOKENS__", json.dumps(TOKENS))

LIST_BODY = json.dumps({"content": [{"invoiceNumber": no, "token": tok, "invoiceDate": "x"}
                                    for no, tok in TOKENS.items()]})


def detail(no, t, **override):
    """真站明細回應的形狀（沒有發票號碼）；日期／金額預設跟清單列一致。"""
    d, amt = LIST_ROWS[no]
    body = {"invoiceDate": d, "invoiceTime": t, "totalAmount": amt, "sellerName": "某某公司"}
    body.update(override)
    return json.dumps(body)


async def _scrape(api, delay=None, list_body=LIST_BODY):
    """api(no) → None＝中斷連線（沒有回應）；str＝回應 body。delay(no) → 回應前延遲秒數。

    所有網路都被 route 攔下，不出網。"""
    async with pw.async_playwright() as p:
        browser = await p.chromium.launch()
        page = await (await browser.new_context()).new_page()

        async def handle(route):
            url = route.request.url
            try:
                if url.endswith("/list.html"):
                    await route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                        body=FIXTURE_HTML)
                elif "searchCarrierInvoice" in url and list_body is not None:
                    await route.fulfill(status=200, content_type="application/json", body=list_body)
                elif "getCarrierInvoiceData" in url:
                    no = NO_BY_TOKEN[json.loads(route.request.post_data)["token"]]
                    if delay:
                        await asyncio.sleep(delay(no))
                    body = api(no)
                    if body is None:
                        await route.abort()
                    else:
                        await route.fulfill(status=200, content_type="application/json", body=body)
                else:
                    await route.abort()
            except Exception:
                pass   # 瀏覽器已關（延遲中的回應）
        await page.route("**/*", handle)
        times = einvoice._InvoiceTimes(page)   # 跟正式流程一樣：查詢（清單 API）前就掛上
        await page.goto(f"{BASE}/list.html")
        await page.wait_for_timeout(300)   # 讓清單 API 回來
        try:
            return await einvoice._parse_current_page(page, since_date="2026-01-01", times=times)
        finally:
            await browser.close()


def _by_no(invoices):
    return {inv["invoice_no"]: inv for inv in invoices}


def test_爬蟲_有回應拿到時間_沒回應或壞JSON是None_品項照抓():
    bodies = {
        "AA00000001": detail("AA00000001", "12:38:00"),
        "BB00000002": None,                                   # 沒有回應
        "CC00000003": "{not json",                            # JSON 壞掉
    }
    invoices, stop = asyncio.run(_scrape(bodies.get))
    by_no = _by_no(invoices)
    assert stop is False and set(by_no) == set(bodies)
    assert by_no["AA00000001"]["time"] == time(12, 38)
    assert by_no["BB00000002"]["time"] is None
    assert by_no["CC00000003"]["time"] is None
    assert [it["name"] for it in by_no["AA00000001"]["items"]] == ["大-冰拿鐵"]
    assert [it["name"] for it in by_no["BB00000002"]["items"]] == ["禦飯糰", "茶葉蛋"]
    assert [it["name"] for it in by_no["CC00000003"]["items"]] == ["紅茶"]


def test_爬蟲_invoiceTime包在巢狀資料裡也找得到_格式不對是None():
    bodies = {
        "AA00000001": json.dumps({"code": 200, "data": json.loads(detail("AA00000001", "08:05:09"))}),
        "BB00000002": detail("BB00000002", "25:00:00"),
        "CC00000003": detail("CC00000003", None),
    }
    by_no = _by_no(asyncio.run(_scrape(bodies.get))[0])
    assert by_no["AA00000001"]["time"] == time(8, 5, 9)
    assert by_no["BB00000002"]["time"] is None and by_no["CC00000003"]["time"] is None
    assert [it["name"] for it in by_no["BB00000002"]["items"]] == ["禦飯糰", "茶葉蛋"]


def test_爬蟲_回應延遲超過寬限且晚到落在下一張的等待期間_絕不拿到別張的時間():
    own = {"AA00000001": "11:11:00", "BB00000002": "12:22:00", "CC00000003": "13:33:00"}
    invoices, _ = asyncio.run(_scrape(lambda no: detail(no, own[no]),
                                      delay=lambda no: einvoice._DETAIL_TIME_GRACE_S + 0.5))
    assert [inv["invoice_no"] for inv in invoices] == list(own)
    for inv in invoices:
        assert inv["time"] in (None, einvoice.parse_invoice_time(own[inv["invoice_no"]])), inv
    assert [it["name"] for it in invoices[1]["items"]] == ["禦飯糰", "茶葉蛋"]


def test_爬蟲_上一張晚到時這張自己的回應照樣拿到():
    own = {"AA00000001": "11:11:00", "BB00000002": "12:22:00", "CC00000003": "13:33:00"}
    slow = {"AA00000001": einvoice._DETAIL_TIME_GRACE_S + 0.3}   # AA 晚到，落在 BB 的等待期間
    by_no = _by_no(asyncio.run(_scrape(lambda no: detail(no, own[no]),
                                       delay=lambda no: slow.get(no, 0)))[0])
    assert by_no["AA00000001"]["time"] is None
    assert by_no["BB00000002"]["time"] == time(12, 22)
    assert by_no["CC00000003"]["time"] == time(13, 33)


def test_爬蟲_回應的日期或金額跟清單列對不上_丟棄():
    bodies = {
        "AA00000001": detail("AA00000001", "11:11:00", totalAmount="43"),        # 金額是別張的
        "BB00000002": detail("BB00000002", "12:22:00", invoiceDate="20260605"),  # 日期是別張的
        "CC00000003": detail("CC00000003", "13:33:00"),
    }
    by_no = _by_no(asyncio.run(_scrape(bodies.get))[0])
    assert by_no["AA00000001"]["time"] is None and by_no["BB00000002"]["time"] is None
    assert by_no["CC00000003"]["time"] == time(13, 33)


def test_爬蟲_清單API沒來_對不到token_全部None_品項照抓():
    invoices, _ = asyncio.run(_scrape(lambda no: detail(no, "12:00:00"), list_body=None))
    assert [inv["time"] for inv in invoices] == [None, None, None]
    assert [it["name"] for it in _by_no(invoices)["BB00000002"]["items"]] == ["禦飯糰", "茶葉蛋"]


def test_爬蟲_沒掛時間收集器_不抓時間也不等():
    async def go():
        async with pw.async_playwright() as p:
            browser = await p.chromium.launch()
            page = await (await browser.new_context()).new_page()

            async def handle(route):
                if route.request.url.endswith("/list.html"):
                    await route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                        body=FIXTURE_HTML)
                else:
                    await route.abort()
            await page.route("**/*", handle)
            await page.goto(f"{BASE}/list.html")
            try:
                return await einvoice._parse_current_page(page, since_date="2026-01-01")
            finally:
                await browser.close()
    invoices, _ = asyncio.run(go())
    assert [inv["time"] for inv in invoices] == [None, None, None]
    assert [it["name"] for it in invoices[0]["items"]] == ["大-冰拿鐵"]
