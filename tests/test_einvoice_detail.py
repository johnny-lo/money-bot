"""einvoice 明細抓取的回歸測試(hermetic,不連網)。

守住的 bug:發票明細開在 Bootstrap modal(同一 SPA URL),舊版用 go_back() 退出
→ 把清單帶走 → 只有第一筆抓得到品項,其餘退化成「賣方+總額」一筆。
此測試用靜態 HTML 重現「點號碼→開 modal+backdrop→關 modal」的互動:
舊行為下第二筆會是空的;修正後每筆都拿到自己的品項。

需要 Playwright(僅容器內有);主機無則整檔 skip。
"""
import asyncio
import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402
import einvoice  # noqa: E402

# 兩張發票;點號碼連結會開出各自的明細 modal(含蓋住清單的 backdrop)。
FIXTURE_HTML = r"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<table border="1">
  <tr><th>序</th><th>條碼</th><th>發票號碼</th><th>發票金額</th><th>發票日期</th></tr>
  <tr><td></td><td>手機條碼</td>
      <td>手機條碼<a title="AA00000001" href="javascript:void(0)" onclick="openModal('AA00000001')">AA00000001</a></td>
      <td>55</td><td>2026年6月5日</td></tr>
  <tr><td></td><td></td><td>萊爾富國際股份有限公司</td></tr>
  <tr><td></td><td>手機條碼</td>
      <td>手機條碼<a title="BB00000002" href="javascript:void(0)" onclick="openModal('BB00000002')">BB00000002</a></td>
      <td>43</td><td>2026年6月4日</td></tr>
  <tr><td></td><td></td><td>全家便利商店股份有限公司</td></tr>
</table>
<script>
const DATA = {
  'AA00000001': [['大-冰拿鐵','1','55','55']],
  'BB00000002': [['禦飯糰','1','30','30'], ['茶葉蛋','1','13','13']],
};
function openModal(no){
  const bd = document.createElement('div');
  bd.id = 'bd'; bd.className = 'simple-modal-backdrop';
  bd.style = 'position:fixed;inset:0;z-index:10;background:rgba(0,0,0,.3)';
  document.body.appendChild(bd);
  const m = document.createElement('div');
  m.className = 'modal fade modal_barcode_detail show';
  m.style = 'position:fixed;inset:0;z-index:20;background:#fff';
  const rows = DATA[no].map(r =>
    `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`).join('');
  m.innerHTML =
    `<a class="close_btn" data-bs-dismiss="modal" href="javascript:void(0)" onclick="closeModal()">關閉</a>`
    + `<table><tr><th>品名</th><th>數量</th><th>單價</th><th>金額</th></tr>${rows}</table>`;
  document.body.appendChild(m);
}
function closeModal(){
  document.querySelectorAll('.modal_barcode_detail.show, #bd').forEach(e => e.remove());
}
</script>
</body></html>"""


async def _scrape_fixture():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await (await browser.new_context()).new_page()
        await page.set_content(FIXTURE_HTML)
        try:
            return await einvoice._parse_current_page(page, since_date="2026-01-01")
        finally:
            await browser.close()


def test_every_invoice_gets_its_own_line_items():
    invoices, stop = asyncio.run(_scrape_fixture())
    assert stop is False
    by_no = {inv["invoice_no"]: inv for inv in invoices}
    assert set(by_no) == {"AA00000001", "BB00000002"}

    # 第一筆有明細(舊版也過)
    assert [it["name"] for it in by_no["AA00000001"]["items"]] == ["大-冰拿鐵"]
    # 第二筆也要有自己的明細 —— 舊版 go_back() 會讓這筆變空(回歸守點)
    assert [it["name"] for it in by_no["BB00000002"]["items"]] == ["禦飯糰", "茶葉蛋"]
    assert by_no["BB00000002"]["items"][0]["amount"] == 30
