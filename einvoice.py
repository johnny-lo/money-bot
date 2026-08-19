"""
einvoice.py — 財政部電子發票同步模組

從手機條碼會員區（einvoice.nat.gov.tw）自動登入並抓取發票，寫入 transactions。

需要環境變數：
  EINVOICE_PHONE_1, EINVOICE_PASSWORD_1
  EINVOICE_PHONE_2, EINVOICE_PASSWORD_2  （可選第二組以上，數字遞增）
  GEMINI_API_KEY, MODEL_NAME              （CAPTCHA 辨識用，已存在）

對外 API：
  sync_invoices(days=1) -> str            （阻塞式，回傳人類可讀摘要訊息）

CLI 測試：
  python -m einvoice                       # 預設抓今天
  python -m einvoice --days 7              # 近 7 天
  python -m einvoice --headful             # 顯示瀏覽器（debug 用）
"""
import os
import re
import base64
import calendar
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from gemini import gemini_image
from database import SessionLocal
from models import Transaction

LOGIN_URL = "https://www.einvoice.nat.gov.tw/accounts/login/mw"
HOME_URL = "https://www.einvoice.nat.gov.tw/"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_CAPTCHA_RETRIES = 4


# ─────────────────── 品名格式化 ───────────────────

def is_code(name: str) -> bool:
    """品名是否為純代號（無中文也無 2+ 連續英文字母）。"""
    name = (name or "").strip()
    if not name:
        return False
    if re.search(r"[一-鿿]", name):
        return False
    if re.search(r"[A-Za-z]{2,}", name):
        return False
    return True


def simplify_seller(seller: str) -> str:
    """精簡賣方名（移除「股份有限公司」「分公司」「事業部」等綴詞）。"""
    if not seller:
        return ""
    s = re.sub(r"(股份有限公司|有限公司|股份公司|公司|商行|商號).*$", "", seller)
    s = re.sub(r"第[一二三四五六七八九十百千\d]+(分公司|分行|門市|店).*$", "", s)
    s = re.sub(r"(事業部|分公司|分店|門市).*$", "", s)
    return s.strip()


def format_item(line_item_name: str, seller: str) -> str:
    """純代號 → '賣方-代號'；真品名 → 直接用。"""
    if is_code(line_item_name):
        short = simplify_seller(seller)
        return f"{short}-{line_item_name}" if short else line_item_name
    return line_item_name


# ─────────────────── 爬蟲（Playwright async）───────────────────

async def _solve_captcha(page) -> str:
    await page.wait_for_selector("img[alt='圖形驗證碼']", timeout=10000)
    src = await page.locator("img[alt='圖形驗證碼']").first.get_attribute("src")
    if not src or not src.startswith("data:image/png;base64,"):
        raise RuntimeError(f"CAPTCHA src 異常：{str(src)[:60]!r}")
    img_bytes = base64.b64decode(src.split(",", 1)[1])
    prompt = (
        "這張圖片是 5 位阿拉伯數字驗證碼，可能有一條橫線穿過。"
        "請只回傳 5 個數字，不要有空白、標點或其他字。"
    )
    raw = gemini_image(prompt, img_bytes, mime_type="image/png").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 5:
        raise RuntimeError(f"Gemini 回傳不是 5 位數字：{raw!r}")
    return digits


async def _detect_error(page) -> str:
    selectors = [
        ".error-message", ".alert-danger", ".alert.alert-danger",
        "[role='alert']", ".invalid-feedback:visible", ".error:visible",
        ".swal2-html-container", ".modal-body",
        ".msg_red", ".msg-error", ".form-text.text-danger",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                txt = (await loc.inner_text()).strip()
                if txt:
                    return f"{sel}: {txt[:100]}"
        except Exception:
            continue
    return ""


async def _enter_login_flow(page):
    await page.goto(HOME_URL, wait_until="networkidle", timeout=30000)
    await page.get_by_text("手機條碼發票查詢", exact=True).first.click()
    await page.wait_for_url("**/accounts/login/**", timeout=30000)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass


async def _login(page, phone: str, password: str) -> bool:
    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        print(f"🔐 登入嘗試 {attempt}/{MAX_CAPTCHA_RETRIES}")
        await _enter_login_flow(page)
        try:
            captcha = await _solve_captcha(page)
            print(f"   CAPTCHA: {captcha}")
        except Exception as e:
            print(f"   ⚠️ 辨識失敗：{e}")
            continue

        await page.fill("#mobile_phone", phone)
        await page.fill("#password", password)
        await page.fill("#captcha", captcha)
        await page.click("#submitBtn")

        # 等 URL 連續 3 秒沒變才算穩定（OAuth 會多次 redirect）
        last_url = page.url
        stable = 0
        for _ in range(30):
            await page.wait_for_timeout(1000)
            try:
                cur = page.url
            except Exception:
                continue
            if cur == last_url:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
                last_url = cur
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PWTimeout:
            pass
        await page.wait_for_timeout(1000)

        url = page.url
        body = ""
        for _ in range(5):
            try:
                body = await page.locator("body").inner_text()
                break
            except Exception:
                await page.wait_for_timeout(1500)

        err = await _detect_error(page)

        if "系統訊息" in body and ("409" in body or "已過期" in body):
            print("   ⚠️ 撞到 409，重試")
            continue
        if "/accounts/login" in url:
            print(f"   ❌ 留在登入頁：{err or '(無錯誤元素)'}")
            if err and ("密碼" in err or "帳號" in err) and "驗證碼" not in err:
                return False
            continue
        if any(kw in body for kw in ["發票清單", "查詢發票", "載具明細", "發票號碼", "消費時間"]):
            print(f"   ✅ 登入成功")
            return True
        print(f"   ❓ 未知狀態 URL={url}，重試")
    return False


_DETAIL_MODAL = ".modal_barcode_detail.show"


async def _fetch_detail_items(page) -> list[dict]:
    # 明細是開在 Bootstrap modal 裡;限定在「目前開啟的 modal」內找品項表,
    # 避免抓到底層清單表或上一筆殘留的表。modal 找不到才退回整頁掃描。
    items = await page.evaluate(r"""() => {
        const scope = document.querySelector('.modal_barcode_detail.show') || document;
        const tables = Array.from(scope.querySelectorAll('table'));
        const target = tables.find(t => {
            const headers = Array.from(t.rows[0]?.cells || []).map(c => c.textContent.trim());
            return headers.includes('品名') && headers.includes('數量') &&
                   headers.includes('單價') && headers.includes('金額') &&
                   t.rows.length > 1;
        });
        if (!target) return [];
        const headers = Array.from(target.rows[0].cells).map(c => c.textContent.trim());
        const out = [];
        for (let i = 1; i < target.rows.length; i++) {
            const cells = Array.from(target.rows[i].cells).map(c => c.textContent.trim());
            if (cells.every(c => !c)) continue;
            const obj = {};
            cells.forEach((c, j) => obj[headers[j]] = c);
            out.push(obj);
        }
        return out;
    }""")
    cleaned = []
    for it in items:
        name = it.get("品名", "").strip()
        price_str = it.get("金額", "0").replace(",", "").strip()
        try:
            amount = int(float(price_str))
        except ValueError:
            amount = 0
        if name:
            cleaned.append({"name": name, "amount": amount})
    return cleaned


async def _close_detail_modal(page) -> None:
    """關閉發票明細 modal(若有開)。

    這是整支爬蟲「只抓得到第一筆明細」的根因修正:明細是開在同一個 SPA URL 上的
    Bootstrap modal,舊版用 page.go_back() 想退出 → 反而把整個清單頁帶走,
    後續發票的號碼連結就消失(或被 modal backdrop 擋住點不到)→ items 空 → 退化成
    只寫「賣方+總額」一筆。正解是關 modal(不換頁)再點下一筆。
    """
    try:
        if await page.locator(_DETAIL_MODAL).count() == 0:
            return
        btn = page.locator(f"{_DETAIL_MODAL} a.close_btn[data-bs-dismiss='modal']").first
        clicked = False
        if await btn.count() > 0:
            try:
                await btn.click(timeout=3000)
                clicked = True
            except Exception:
                pass
        if not clicked:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
        # condition-based 等 modal 收起(class 'show' 消失),別死等固定秒數
        try:
            await page.wait_for_selector(_DETAIL_MODAL, state="hidden", timeout=5000)
        except PWTimeout:
            pass
    except Exception:
        pass


async def _parse_current_page(page, since_date: str) -> tuple[list[dict], bool]:
    """回傳 (該頁發票列表, 是否要停止翻頁)。發票按日期 desc 排序，遇到 < since_date 即 stop。"""
    raw_rows = await page.evaluate(r"""() => {
        const tables = Array.from(document.querySelectorAll('table'));
        const target = tables.find(t => {
            if (!t.rows || t.rows.length < 2) return false;
            const header = t.rows[0].textContent || '';
            return header.includes('發票號碼') && header.includes('發票金額');
        });
        if (!target) return [];
        const rows = [];
        for (let i = 1; i < target.rows.length; i++) {
            rows.push(Array.from(target.rows[i].cells).map(c => c.textContent.trim()));
        }
        return rows;
    }""")

    invoices = []
    stop = False
    i = 0
    while i < len(raw_rows):
        row = raw_rows[i]
        if len(row) >= 5 and row[2].startswith("手機條碼") and row[3]:
            inv_num = re.sub(r"^手機條碼", "", row[2]).strip()
            amount_str = row[3].replace(",", "").strip()
            try:
                amount = int(amount_str)
            except ValueError:
                amount = 0
            m = re.match(r"(\d+)年(\d+)月(\d+)日", row[4])
            inv_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else row[4]
            if since_date and inv_date < since_date:
                stop = True
                break
            seller = ""
            if i + 1 < len(raw_rows):
                for cell in raw_rows[i + 1]:
                    if cell and not cell.startswith("手機條碼") and len(cell) > 2:
                        seller = cell
                        break
            invoices.append({
                "invoice_no": inv_num,
                "amount": amount,
                "date": inv_date,
                "seller": seller,
                "items": [],
            })
            i += 2
        else:
            i += 1

    # 點進每筆抓明細:明細開在 Bootstrap modal(同一 SPA URL,不換頁)。
    # 流程 = 點號碼 → 等 modal 開 → 讀品項 → 關 modal → 下一筆。
    # 嚴禁 go_back():那會把 SPA 清單整個帶走,只剩第一筆抓得到明細(本次修正的根因)。
    for inv in invoices:
        try:
            link = page.locator(f"a:text-is('{inv['invoice_no']}')").first
            if await link.count() == 0:
                continue
            await link.click()
            # 明細是開 modal,不是換 URL → 等 modal 真的出現
            await page.wait_for_selector(_DETAIL_MODAL, state="visible", timeout=10000)
            await page.wait_for_timeout(400)
            inv["items"] = await _fetch_detail_items(page)
            print(f"     {inv['invoice_no']} | {inv['seller'][:14]} | {len(inv['items'])} 品項")
        except Exception as e:
            print(f"     ⚠️ {inv['invoice_no']} 抓明細失敗：{type(e).__name__}: {e}")
        finally:
            # 不論成功與否都要把 modal 關掉,否則 backdrop 會擋住下一筆的點擊
            await _close_detail_modal(page)
    return invoices, stop


# 真正的翻頁是 Bootstrap 分頁 a.page-link「下一頁」(父 li 未 disabled);舊版用
# button[aria-label]/rel=next 從來沒中過,所以多頁時只抓得到第 1 頁。
_NEXT_PAGE_FIND = r"""() => {
    const a = Array.from(document.querySelectorAll('a.page-link')).find(a =>
        a.textContent.includes('下一頁') && !(a.closest('li')?.classList.contains('disabled')));
    return !!a;
}"""
_NEXT_PAGE_CLICK = r"""() => {
    const a = Array.from(document.querySelectorAll('a.page-link')).find(a =>
        a.textContent.includes('下一頁') && !(a.closest('li')?.classList.contains('disabled')));
    if (a) { a.click(); return true; } return false;
}"""
# 目前作用中的頁碼(用來判斷「下一頁」有沒有真的前進 —— 最後一頁的下一頁不一定 disabled)
_ACTIVE_PAGE_JS = r"""() => {
    const a = document.querySelector('li.page-item.active .page-link, li.active .page-link');
    return a ? a.textContent.trim() : null;
}"""


async def _click_day_cell(page, day: int) -> bool:
    """點 vue-datepicker 當前顯示月份裡、非鄰月(offset)的某一天。"""
    cells = page.locator(".dp__cell_inner.dp__pointer:not(.dp__cell_offset)")
    for i in range(await cells.count()):
        c = cells.nth(i)
        if ((await c.text_content()) or "").strip() == str(day):
            await c.click()
            return True
    return False


async def _set_query_month(page, year: int, month: int) -> None:
    """把『查詢發票日期起迄』設成指定單月 1 號 ~ 月底。

    政府站限制:每次查詢區間須為『同一個月』(跨月會被擋:請一併點選起日及迄日)。
    操作 vue-datepicker — 點開 → 導覽到目標月 → 點 1 號(起)+ 該月最後一天(迄),
    auto-apply 自動套用(此站日曆無確認鈕)。導覽用 aria-label 上個月/下個月。
    """
    last_day = calendar.monthrange(year, month)[1]
    await page.click("#dp-input-searchInvoiceDate")
    await page.wait_for_timeout(600)
    for _ in range(24):  # 導覽到目標月(上限保護,避免死迴圈)
        hdr = await page.evaluate(
            "() => Array.from(document.querySelectorAll('.dp__month_year_select'))"
            ".map(e=>e.textContent.trim()).join(' ')")
        mm = re.search(r"(\d+)月", hdr)
        yy = re.search(r"(\d+)年", hdr)
        if not (mm and yy):
            break
        cur_y, cur_m = int(yy.group(1)), int(mm.group(1))
        if (cur_y, cur_m) == (year, month):
            break
        prev = (year, month) < (cur_y, cur_m)
        await page.click(f'button.dp--arrow-btn-nav[aria-label="{"上個月" if prev else "下個月"}"]')
        await page.wait_for_timeout(350)
    await _click_day_cell(page, 1)          # 起日
    await page.wait_for_timeout(250)
    await _click_day_cell(page, last_day)   # 迄日 → auto-apply
    await page.wait_for_timeout(500)
    try:
        await page.wait_for_selector('[class*="dp__menu"]', state="hidden", timeout=4000)
    except PWTimeout:
        pass


async def _scrape_carrier(phone: str, password: str, days: int, headless: bool = True,
                          month: tuple[int, int] | None = None) -> list[dict]:
    """單一載具完整流程：登入 → 搜尋 → 翻頁抓明細。回傳發票列表。

    month=(year, month):回填模式,把查詢區間設成該『單月』(政府站限制同月)抓整月;
    None:用預設區間(本月),以 days 推算 since 做客端早停(每日同步用)。
    """
    if month:
        since = f"{month[0]}-{month[1]:02d}-01"
    else:
        end_date = datetime.now().date()
        since = (end_date - timedelta(days=days - 1)).isoformat()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=UA, locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1366, "height": 900},
        )
        page = await ctx.new_page()
        try:
            if not await _login(page, phone, password):
                return []
            if month:
                await _set_query_month(page, month[0], month[1])
            await page.locator("button.blue_btn", has_text="查詢").first.click()
            await page.wait_for_timeout(2000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass
            await page.wait_for_timeout(1500)

            all_invoices = []
            page_no = 1
            while True:
                invs, stop = await _parse_current_page(page, since_date=since)
                print(f"   📄 第 {page_no} 頁：{len(invs)} 筆")
                all_invoices.extend(invs)
                if stop:
                    break
                if not await page.evaluate(_NEXT_PAGE_FIND):
                    break
                active_before = await page.evaluate(_ACTIVE_PAGE_JS)
                try:
                    await page.evaluate(_NEXT_PAGE_CLICK)
                    await page.wait_for_timeout(1500)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except PWTimeout:
                        pass
                except Exception:
                    break
                # 最後一頁的「下一頁」不一定會 disabled;若作用中頁碼沒前進 = 已到底,停。
                # (否則會一直重抓最後一頁,直到撞 page_no 上限 —— 浪費又可能截斷)
                if active_before is not None and \
                        await page.evaluate(_ACTIVE_PAGE_JS) == active_before:
                    break
                page_no += 1
                if page_no > 60:
                    break
            return all_invoices
        finally:
            await browser.close()


# ─────────────────── DB 寫入 ───────────────────

def _save_invoices(invoices: list[dict], source: str | None = None) -> tuple[int, int, list[dict]]:
    """寫入 DB，去重（同一張發票已寫過就跳過）。回傳 (新增發票數, 新增品項數, 新增品項清單)。"""
    if not invoices:
        return 0, 0, []
    db = SessionLocal()
    try:
        new_inv = 0
        new_items = 0
        added: list[dict] = []
        for inv in invoices:
            inv_no = inv["invoice_no"]
            if db.query(Transaction).filter(Transaction.invoice_no == inv_no).first():
                continue  # 已抓過
            try:
                inv_dt = datetime.strptime(inv["date"], "%Y-%m-%d")
            except ValueError:
                inv_dt = datetime.now()

            items = inv.get("items") or []
            wrote = False
            for it in items:
                if it["amount"] == 0:
                    continue  # 折扣 / 促銷標記
                name = format_item(it["name"], inv["seller"])
                tx = Transaction(
                    item=name,
                    price=it["amount"],
                    invoice_no=inv_no,
                    source=source,
                    created_at=inv_dt,
                )
                db.add(tx)
                new_items += 1
                added.append({"item": name, "price": it["amount"], "date": inv["date"]})
                wrote = True
            # 明細抓不到 → 保底寫一筆 = 賣方名 + 發票總額
            if not wrote and inv["amount"] > 0:
                name = simplify_seller(inv["seller"]) or inv_no
                tx = Transaction(
                    item=name,
                    price=inv["amount"],
                    invoice_no=inv_no,
                    source=source,
                    created_at=inv_dt,
                )
                db.add(tx)
                new_items += 1
                added.append({"item": name, "price": inv["amount"], "date": inv["date"]})
            new_inv += 1
        db.commit()
        return new_inv, new_items, added
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ─────────────────── 對外 API ───────────────────

def _list_carriers() -> list[tuple[int, str, str]]:
    """從環境變數蒐集所有載具。回傳 [(編號, 手機, 密碼), ...]"""
    carriers = []
    for i in range(1, 10):
        phone = os.getenv(f"EINVOICE_PHONE_{i}")
        password = os.getenv(f"EINVOICE_PASSWORD_{i}")
        if phone and password:
            carriers.append((i, phone, password))
    return carriers


def sync_invoices(days: int = 1, headless: bool = True) -> dict:
    """同步所有設定載具的發票。回傳 {"summary": str, "new_items": list[dict]}。"""
    carriers = _list_carriers()
    if not carriers:
        return {"summary": "⚠️ 未設定任何載具（EINVOICE_PHONE_1 / EINVOICE_PASSWORD_1）", "new_items": []}

    lines = [f"🧾 發票同步（最近 {days} 天）"]
    total_new_inv = 0
    total_new_items = 0
    all_added: list[dict] = []
    for label, phone, password in carriers:
        masked = f"{phone[:4]}***{phone[-2:]}"
        try:
            invoices = asyncio.run(_scrape_carrier(phone, password, days, headless=headless))
            new_inv, new_items, added = _save_invoices(invoices, source=f"載具{label}")
            total_new_inv += new_inv
            total_new_items += new_items
            all_added.extend(added)
            lines.append(
                f"  載具{label} {masked}：抓 {len(invoices)} 張、新增 {new_inv} 張（{new_items} 品項）"
            )
        except Exception as e:
            lines.append(f"  載具{label} {masked}：失敗 - {type(e).__name__}: {e}")
    lines.append(f"📊 總計新增：{total_new_inv} 張發票 / {total_new_items} 筆品項")
    summary = "\n".join(lines)
    print(summary)
    return {"summary": summary, "new_items": all_added}


# ─────────────────── CLI ───────────────────

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()
    print(sync_invoices(days=args.days, headless=not args.headful)["summary"])
