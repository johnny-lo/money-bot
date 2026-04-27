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


async def _fetch_detail_items(page) -> list[dict]:
    items = await page.evaluate(r"""() => {
        const tables = Array.from(document.querySelectorAll('table'));
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

    # 點進每筆抓明細
    for inv in invoices:
        try:
            link = page.locator(f"a:text-is('{inv['invoice_no']}')").first
            if await link.count() == 0:
                continue
            await link.click()
            await page.wait_for_url("**/detail**", timeout=10000)
            await page.wait_for_timeout(800)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                pass
            inv["items"] = await _fetch_detail_items(page)
            print(f"     {inv['invoice_no']} | {inv['seller'][:14]} | {len(inv['items'])} 品項")
            await page.go_back()
            await page.wait_for_timeout(1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                pass
        except Exception as e:
            print(f"     ⚠️ {inv['invoice_no']} 抓明細失敗：{type(e).__name__}")
            try:
                await page.go_back()
                await page.wait_for_timeout(1000)
            except Exception:
                pass
    return invoices, stop


async def _scrape_carrier(phone: str, password: str, days: int, headless: bool = True) -> list[dict]:
    """單一載具完整流程：登入 → 搜尋 → 翻頁抓明細。回傳發票列表。"""
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
                # 找下一頁
                next_btn = None
                for sel in [
                    'button[aria-label="下一頁"]:not([disabled])',
                    'a[rel="next"]',
                    'button:has-text("下一頁"):not([disabled])',
                ]:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0 and await loc.is_enabled():
                            next_btn = loc
                            break
                    except Exception:
                        continue
                if not next_btn:
                    break
                try:
                    await next_btn.click()
                    await page.wait_for_timeout(1500)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except PWTimeout:
                        pass
                    page_no += 1
                    if page_no > 30:
                        break
                except Exception:
                    break
            return all_invoices
        finally:
            await browser.close()


# ─────────────────── DB 寫入 ───────────────────

def _save_invoices(invoices: list[dict]) -> tuple[int, int]:
    """寫入 DB，去重（同一張發票已寫過就跳過）。回傳 (新增發票數, 新增品項數)。"""
    if not invoices:
        return 0, 0
    db = SessionLocal()
    try:
        new_inv = 0
        new_items = 0
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
                tx = Transaction(
                    item=format_item(it["name"], inv["seller"]),
                    price=it["amount"],
                    invoice_no=inv_no,
                    created_at=inv_dt,
                )
                db.add(tx)
                new_items += 1
                wrote = True
            # 明細抓不到 → 保底寫一筆 = 賣方名 + 發票總額
            if not wrote and inv["amount"] > 0:
                tx = Transaction(
                    item=simplify_seller(inv["seller"]) or inv_no,
                    price=inv["amount"],
                    invoice_no=inv_no,
                    created_at=inv_dt,
                )
                db.add(tx)
                new_items += 1
            new_inv += 1
        db.commit()
        return new_inv, new_items
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


def sync_invoices(days: int = 1, headless: bool = True) -> str:
    """同步所有設定載具的發票。回傳人類可讀摘要訊息（給 LINE/排程 log 用）。"""
    carriers = _list_carriers()
    if not carriers:
        return "⚠️ 未設定任何載具（EINVOICE_PHONE_1 / EINVOICE_PASSWORD_1）"

    lines = [f"🧾 發票同步（最近 {days} 天）"]
    total_new_inv = 0
    total_new_items = 0
    for label, phone, password in carriers:
        masked = f"{phone[:4]}***{phone[-2:]}"
        try:
            invoices = asyncio.run(_scrape_carrier(phone, password, days, headless=headless))
            new_inv, new_items = _save_invoices(invoices)
            total_new_inv += new_inv
            total_new_items += new_items
            lines.append(
                f"  載具{label} {masked}：抓 {len(invoices)} 張、新增 {new_inv} 張（{new_items} 品項）"
            )
        except Exception as e:
            lines.append(f"  載具{label} {masked}：失敗 - {type(e).__name__}: {e}")
    lines.append(f"📊 總計新增：{total_new_inv} 張發票 / {total_new_items} 筆品項")
    summary = "\n".join(lines)
    print(summary)
    return summary


# ─────────────────── CLI ───────────────────

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()
    print(sync_invoices(days=args.days, headless=not args.headful))
