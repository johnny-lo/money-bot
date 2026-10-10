"""probe 的安全帶：在 Playwright 網路層數「送出登入表單」次數，超過預算直接 abort。

擋得住：worktree 程式「不小心」的重試迴圈（只要請求帶著手機號碼送往財政部，就算一次）。
擋不住：刻意繞過的程式——它跟被測程式在同一個行程、容器有網路，可以還原 patch 或不走 Playwright。
所以跨呼叫的真正上限放在主機端 bin/probe（每事件 3 次呼叫、每次容器 timeout），這裡只是第一道。
必須在 import 被測程式之前 install()。
"""
import re
from pathlib import Path
from urllib.parse import urlparse

GUARDED_HOST = "einvoice.nat.gov.tw"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def is_credential_submit(method: str, host: str, post_data: str, phones: list[str]) -> bool:
    if method.upper() == "GET" or not host.endswith(GUARDED_HOST):
        return False
    return any(p and p in (post_data or "") for p in phones)


def take_budget(path: Path, limit: int = 3) -> bool:
    used = int(path.read_text()) if path.exists() else 0
    if used >= limit:
        return False
    path.write_text(str(used + 1))
    return True


def mask(text: str, phones: list[str]) -> str:
    for p in phones:
        if p:
            text = text.replace(p, p[:4] + "****" + p[-2:])
    return _EMAIL.sub("<email>", text)


async def _dump(contexts: list, dump_dir: Path, phones: list[str]) -> None:
    """把每個頁面的 URL、遮罩後內文、截圖存到 dump_dir 給 Claude 用 Read 看。"""
    dump_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for ctx in contexts:
        for page in ctx.pages:
            n += 1
            try:
                body = await page.locator("body").inner_text()
            except Exception as e:
                body = f"(讀不到 body：{e})"
            (dump_dir / f"page{n}.txt").write_text(f"URL={page.url}\n\n{mask(body, phones)}",
                                                   encoding="utf-8")
            try:
                await page.screenshot(path=str(dump_dir / f"page{n}.png"), full_page=True)
            except Exception:
                pass
    if n:
        print(f"📸 已存 {n} 個頁面到 {dump_dir}", flush=True)


def install(budget_path: Path, phones: list[str], dump_dir: Path, limit: int = 3):
    """patch Playwright：每個 context 自動掛 guard、browser 關閉前自動存頁面。回傳 uninstall()。"""
    from playwright.async_api import Browser, BrowserContext

    contexts: list = []
    orig = {"route": BrowserContext.route, "unroute": BrowserContext.unroute,
            "new_context": Browser.new_context, "new_page": Browser.new_page,
            "close": Browser.close}

    async def _guard(route, request):
        host = urlparse(request.url).hostname or ""
        if is_credential_submit(request.method, host, request.post_data or "", phones):
            if not take_budget(budget_path, limit):
                print(f"⛔ 登入預算用完（這次 probe 最多 {limit} 次送出），已在網路層攔截", flush=True)
                await route.abort()
                return
            print("🔑 送出登入表單（計入預算）", flush=True)
        await route.fallback()

    async def _route(self, url, handler, **kw):
        await orig["unroute"](self, "**/*", _guard)
        await orig["route"](self, url, handler, **kw)
        await orig["route"](self, "**/*", _guard)

    async def _new_context(self, *a, **kw):
        ctx = await orig["new_context"](self, *a, **kw)
        await orig["route"](ctx, "**/*", _guard)
        contexts.append(ctx)
        return ctx

    async def _new_page(self, *a, **kw):   # browser.new_page() 會自建 context，也要經過 guard
        ctx = await _new_context(self, *a, **kw)
        return await ctx.new_page()

    async def _close(self, *a, **kw):
        # 被測程式在 finally 關 browser——關之前一律存頁面（成功也存，成本只是幾張截圖）
        await _dump(contexts, dump_dir, phones)
        return await orig["close"](self, *a, **kw)

    BrowserContext.route = _route
    Browser.new_context = _new_context
    Browser.new_page = _new_page
    Browser.close = _close

    def uninstall():
        BrowserContext.route = orig["route"]
        Browser.new_context = orig["new_context"]
        Browser.new_page = orig["new_page"]
        Browser.close = orig["close"]

    return uninstall
