"""刷卡比對 orchestrator：抓信 → 解密解析 → upsert → 中信店名讀圖 → 收據補店名 → 比對 → 補品牌 → 分頁指派清單。"""
from datetime import date, timedelta

from app_secrets import get_secret
from database import SessionLocal

from . import brand, config, gmail, hints, merchant_ocr, parse, pdf, repo
from . import match as matcher
from .repo import branded
from .types import RawMail, WeeklyResult


def run_weekly(today: date, db=None) -> WeeklyResult:
    own = db is None
    db = db or SessionLocal()
    try:
        return _run(db, today)
    finally:
        if own:
            db.close()


def relist(today: date, db=None) -> WeeklyResult:
    """把已列出、還沒處理的未配對刷卡收回，照新分組重列。不連 Gmail。"""
    own = db is None
    db = db or SessionLocal()
    try:
        start = repo.max_page(db, today.isoformat())      # 先讀：unlist 後舊批次號消失，會被重用
        repo.unlist(db)
        res = WeeklyResult()
        _list(db, today, res, start)
        return res
    finally:
        if own:
            db.close()


def _soft(db, what: str, fn, default=None):
    """店名讀圖與品牌是加分項：失敗只印警告，不擋清單（session 壞了就 rollback，後面的查詢才能繼續）。"""
    try:
        return fn()
    except Exception as e:
        print(f"⚠️ {what}失敗：{e}", flush=True)
        try:
            db.rollback()
        except Exception:
            pass
        return default


def _ocr_ctbc(db, mail: RawMail, charges: list, nid: str) -> int:
    """中信帳單的中文店名是圖片：讀圖後用 (刷卡日, 入帳日, 金額, 卡號) 對回缺店名的列。回補了幾筆。"""
    missing = repo.missing_merchant_lines(db, mail.message_id)
    todo = [c for c in charges if c.line_no in missing]
    if not todo:
        return 0
    want = {(c.charge_date, c.post_date, c.amount, c.card_last4) for c in todo}
    cells = [(key, bm) for key, bm in pdf.ctbc_merchant_cells(mail.pdf, nid) if key in want]
    if not cells:                                            # 缺店名的列沒有對到格：不花一次讀圖
        return 0
    names = merchant_ocr.read_names([bm for _, bm in cells])
    got = merchant_ocr.assign_by_key(todo, [(key, n) for (key, _), n in zip(cells, names)])
    return repo.set_merchant_by_line(db, mail.message_id, got) if got else 0


def _receipts(since: date | None) -> list:
    """各收據來源（第三欄決定用哪個 parser）抓到的收據。"""
    out = []
    for sender, kw, parser in config.RECEIPT_SOURCES:
        fn = parse.RECEIPT_PARSERS[parser]
        out += [r for m in gmail.fetch(sender, kw, since) if (r := fn(m.text))]
    return out


def _fill_brands(db) -> int:
    """還沒有品牌對照的店名問一次、存起來。回新增幾筆。"""
    raws = repo.missing_brands(db)
    if not raws:
        return 0
    got = brand.suggest(raws)
    return repo.save_brands(db, got) if got else 0


def _list(db, today: date, res: WeeklyResult, start_page: int = 0) -> None:
    """列出還沒進清單卡的未配對刷卡：分組後各組各自分頁，批次號 '<day>-<n>' 跨組連續。清單顯示品牌。"""
    _soft(db, "店名換品牌", lambda: _fill_brands(db))
    brands = _soft(db, "讀品牌對照", lambda: repo.brand_map(db), {})
    listed = [(i, branded(c, brands)) for i, c in
              repo.unlisted(db, today - timedelta(days=config.LIST_LAG_DAYS), config.LIST_FROM)]
    res.total = sum(c.amount for _, c in listed)
    if not listed:
        return
    since = min(c.charge_date for _, c in listed) - timedelta(days=1)
    txs, timed = repo.load_hints(db, since), repo.load_time_hints(db, since)
    n = start_page
    for key, items in hints.arrange(listed, txs, repo.all_charges(db), timed):
        for p in range(0, len(items), config.PAGE_SIZE):
            chunk = items[p:p + config.PAGE_SIZE]
            n += 1
            batch = f"{today.isoformat()}-{n}"
            repo.assign_batch(db, [i for i, _, _ in chunk], batch)
            res.pages.append((batch, key, chunk))


def _run(db, today: date) -> WeeklyResult:
    nid = get_secret("NATIONAL_ID")
    if not nid:
        raise RuntimeError("national_id secret 是空的，解不開銀行 PDF")
    lookback = today - timedelta(days=config.LOOKBACK_DAYS)
    res = WeeklyResult()

    full_fetch = False
    for source, (sender, kw) in config.CARD_SOURCES.items():
        since = lookback if repo.has_source(db, source) else None     # 逐來源判斷首跑
        full_fetch = full_fetch or since is None
        for mail in gmail.fetch(sender, kw, since):
            if mail.pdf is None:
                res.unparsed_mails += 1
                continue
            text = pdf.extract_text(mail.pdf, nid)
            if text is None:
                res.failed_mails += 1
                continue
            charges = parse.PARSERS[source](text)
            if not charges:
                res.unparsed_mails += 1
                continue
            repo.upsert_charges(db, mail.message_id, charges)
            if source == "ctbc_statement":
                _soft(db, "中信店名讀圖", lambda: _ocr_ctbc(db, mail, charges, nid))

    receipts = _receipts(None if full_fetch else lookback)
    if receipts:
        repo.set_merchant(db, matcher.enrich(repo.pending(db, today), receipts))

    pend = repo.pending(db, today)
    if pend:
        used = repo.used_group_keys(db)
        start = min(c.charge_date for _, c in pend) - timedelta(days=3)
        groups = [g for g in repo.load_groups(db, start) if g.key not in used]
        repo.mark_matched(db, matcher.match(pend, groups))

    _list(db, today, res, repo.max_page(db, today.isoformat()))
    return res


def backfill_merchants(today: date, db=None) -> dict:
    """一次性補舊資料：所有中信帳單重新讀圖、所有收據補店名、最後補品牌。只補店名還空著的列。
    回 {"ocr": 讀圖補了幾筆, "receipts": 收據補了幾筆, "brands": 新增幾筆品牌對照}。"""
    nid = get_secret("NATIONAL_ID")
    if not nid:
        raise RuntimeError("national_id secret 是空的，解不開銀行 PDF")
    own = db is None
    db = db or SessionLocal()
    try:
        ocr = 0
        sender, kw = config.CARD_SOURCES["ctbc_statement"]
        for mail in gmail.fetch(sender, kw, None):
            if mail.pdf is None:
                continue
            text = pdf.extract_text(mail.pdf, nid)
            charges = parse.PARSERS["ctbc_statement"](text) if text is not None else []
            if charges:
                ocr += _soft(db, "中信店名讀圖", lambda: _ocr_ctbc(db, mail, charges, nid), 0)
        found = {}
        receipts = _receipts(None)
        if receipts:
            found = matcher.enrich(repo.missing_merchant(db), receipts)
            if found:
                repo.set_merchant(db, found)
        return {"ocr": ocr, "receipts": len(found), "brands": _soft(db, "店名換品牌", lambda: _fill_brands(db), 0)}
    finally:
        if own:
            db.close()
