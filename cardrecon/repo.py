"""card_charges 的唯一 DB 存取層。upsert 是唯一寫入咽喉點；補記寫 transactions 也在這裡。"""
from dataclasses import asdict
from datetime import date, datetime, time, timedelta

from models import CardCharge, Transaction

from . import match as matcher
from .types import Charge, RecordResult, TxGroup


def _to_charge(r) -> Charge:
    return Charge(source=r.source, card_last4=r.card_last4, charge_date=r.charge_date, amount=r.amount,
                  line_no=r.line_no, charge_time=r.charge_time, post_date=r.post_date, region=r.region,
                  merchant=r.merchant, pay_method=r.pay_method)


def has_source(db, source: str) -> bool:
    return db.query(CardCharge.id).filter(CardCharge.source == source).first() is not None


def max_page(db, day: str) -> int:
    """當天已用過的最大頁碼（批次名 '<day>-<n>'），沒有回 0。"""
    prefix, best = f"{day}-", 0
    for (b,) in db.query(CardCharge.batch).filter(CardCharge.batch.like(f"{prefix}%")).distinct().all():
        tail = (b or "")[len(prefix):]
        if b and b.startswith(prefix) and tail.isdigit():
            best = max(best, int(tail))
    return best


def upsert_charges(db, message_id: str, charges: list[Charge]) -> int:
    """新的才插；已存在（同信同行）一律跳過，不覆蓋 status（避免把忽略/已補記蓋回 unmatched）。"""
    existing = {n for (n,) in db.query(CardCharge.line_no).filter(CardCharge.message_id == message_id).all()}
    new = 0
    for c in charges:
        if c.line_no in existing:
            continue
        db.add(CardCharge(message_id=message_id, status="unmatched", **asdict(c)))
        new += 1
    db.commit()
    return new


def _by_ids(db, ids):
    return db.query(CardCharge).filter(CardCharge.id.in_(list(ids))).all() if ids else []


def set_merchant(db, mapping: dict[int, str]) -> None:
    for r in _by_ids(db, mapping):
        r.merchant = mapping[r.id]
    db.commit()


def mark_matched(db, mapping: dict[int, str]) -> None:
    for r in _by_ids(db, mapping):
        r.status, r.matched_key = "matched", mapping[r.id]
    db.commit()


def pending(db, until: date) -> list[tuple[int, Charge]]:
    rows = (db.query(CardCharge).filter(CardCharge.status == "unmatched", CardCharge.charge_date <= until)
            .order_by(CardCharge.charge_date, CardCharge.id).all())
    return [(r.id, _to_charge(r)) for r in rows]


def unlisted(db, until: date, since: date) -> list[tuple[int, Charge]]:
    """還沒列進任何清單卡的未配對刷卡（已列過的留在原卡上處理，不重列）。"""
    rows = (db.query(CardCharge).filter(CardCharge.status == "unmatched", CardCharge.batch.is_(None),
                                        CardCharge.charge_date <= until, CardCharge.charge_date >= since)
            .order_by(CardCharge.charge_date, CardCharge.id).all())
    return [(r.id, _to_charge(r)) for r in rows]


def used_group_keys(db) -> set[str]:
    return {k for (k,) in db.query(CardCharge.matched_key).filter(CardCharge.matched_key.isnot(None)).all()}


def load_groups(db, since: date) -> list[TxGroup]:
    rows = (db.query(Transaction.id, Transaction.invoice_no, Transaction.created_at, Transaction.price)
            .filter(Transaction.created_at >= datetime.combine(since, time())).all())
    return matcher.group_transactions([tuple(r) for r in rows])


def assign_batch(db, ids: list[int], batch: str) -> None:
    for r in _by_ids(db, ids):
        r.batch = batch
    db.commit()


def _batch_rows(db, batch: str):
    return db.query(CardCharge).filter(CardCharge.batch == batch).order_by(CardCharge.charge_date, CardCharge.id).all()


def batch_items(db, batch: str) -> list[tuple[int, Charge, str]]:
    return [(r.id, _to_charge(r), r.status) for r in _batch_rows(db, batch)]


def ignore(db, batch: str, ids: list[int]) -> int:
    ids, n = set(ids), 0
    for r in _batch_rows(db, batch):
        if r.id in ids and r.status == "unmatched":
            r.status = "ignored"
            n += 1
    db.commit()
    return n


def transaction_fields(c: Charge) -> dict:
    hh, mm = (int(x) for x in c.charge_time.split(":")) if c.charge_time else (12, 0)
    return {"item": c.merchant or f"信用卡消費（{c.region}）", "price": c.amount, "source": "信用卡",
            "created_at": datetime.combine(c.charge_date, time(hh, mm)),
            "invoice_no": None, "seller": None, "category": None}


def record(db, batch: str) -> RecordResult:
    """整批補記。先重比（列卡後發票可能才進來），配到的改 matched；其餘寫 transactions。一次 commit，失敗 rollback。"""
    rows = [r for r in _batch_rows(db, batch) if r.status == "unmatched"]
    if not rows:
        return RecordResult(0, 0, 0)
    try:
        items = [(r.id, _to_charge(r)) for r in rows]
        since = min(c.charge_date for _, c in items) - timedelta(days=3)
        used = used_group_keys(db)
        found = matcher.match(items, [g for g in load_groups(db, since) if g.key not in used])
        recorded = total = 0
        for r in rows:
            if r.id in found:
                r.status, r.matched_key = "matched", found[r.id]
                continue
            tx = Transaction(**transaction_fields(_to_charge(r)))
            db.add(tx)
            db.flush()
            r.status, r.matched_key = "recorded", f"id{tx.id}"
            recorded += 1
            total += r.amount
        db.commit()
        return RecordResult(recorded, total, len(found))
    except Exception:
        db.rollback()
        raise
