"""刷卡比對 orchestrator：抓信 → 解密解析 → upsert → 收據補店名 → 比對 → 分頁指派清單。"""
from datetime import date, timedelta

from app_secrets import get_secret
from database import SessionLocal

from . import config, gmail, hints, parse, pdf, repo
from . import match as matcher
from .types import WeeklyResult


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
        repo.unlist(db)
        res = WeeklyResult()
        _list(db, today, res)
        return res
    finally:
        if own:
            db.close()


def _list(db, today: date, res: WeeklyResult) -> None:
    """列出還沒進清單卡的未配對刷卡：分組後各組各自分頁，批次號 '<day>-<n>' 跨組連續。"""
    listed = repo.unlisted(db, today - timedelta(days=config.LIST_LAG_DAYS), config.LIST_FROM)
    res.total = sum(c.amount for _, c in listed)
    if not listed:
        return
    txs = repo.load_hints(db, min(c.charge_date for _, c in listed) - timedelta(days=1))
    n = repo.max_page(db, today.isoformat())
    for key, items in hints.arrange(listed, txs, repo.all_charges(db)):
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

    receipt_since = None if full_fetch else lookback
    receipts = [r for sender, kw in config.RECEIPT_SOURCES
                for m in gmail.fetch(sender, kw, receipt_since) if (r := parse.parse_autopass(m.text))]
    if receipts:
        repo.set_merchant(db, matcher.enrich(repo.pending(db, today), receipts))

    pend = repo.pending(db, today)
    if pend:
        used = repo.used_group_keys(db)
        start = min(c.charge_date for _, c in pend) - timedelta(days=3)
        groups = [g for g in repo.load_groups(db, start) if g.key not in used]
        repo.mark_matched(db, matcher.match(pend, groups))

    _list(db, today, res)
    return res
