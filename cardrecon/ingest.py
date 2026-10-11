"""刷卡比對 orchestrator：抓信 → 解密解析 → upsert → 收據補店名 → 比對 → 分頁指派清單。"""
from datetime import date, timedelta

from app_secrets import get_secret
from database import SessionLocal

from . import config, gmail, parse, pdf, repo
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


def _run(db, today: date) -> WeeklyResult:
    nid = get_secret("NATIONAL_ID")
    if not nid:
        raise RuntimeError("national_id secret 是空的，解不開銀行 PDF")
    since = today - timedelta(days=config.LOOKBACK_DAYS) if repo.has_any(db) else None
    res = WeeklyResult()

    for source, (sender, kw) in config.CARD_SOURCES.items():
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

    receipts = [r for sender, kw in config.RECEIPT_SOURCES
                for m in gmail.fetch(sender, kw, since) if (r := parse.parse_autopass(m.text))]
    if receipts:
        repo.set_merchant(db, matcher.enrich(repo.pending(db, today), receipts))

    pend = repo.pending(db, today)
    if pend:
        used = repo.used_group_keys(db)
        start = min(c.charge_date for _, c in pend) - timedelta(days=3)
        groups = [g for g in repo.load_groups(db, start) if g.key not in used]
        repo.mark_matched(db, matcher.match(pend, groups))

    listed = repo.unlisted(db, today - timedelta(days=config.LIST_LAG_DAYS), config.LIST_FROM)
    for p in range(0, len(listed), config.PAGE_SIZE):
        chunk = listed[p:p + config.PAGE_SIZE]
        batch = f"{today.isoformat()}-{p // config.PAGE_SIZE + 1}"
        repo.assign_batch(db, [i for i, _ in chunk], batch)
        res.pages.append((batch, chunk))
    res.total = sum(c.amount for _, c in listed)
    return res
