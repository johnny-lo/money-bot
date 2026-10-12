"""card_charges 的唯一 DB 存取層。upsert 是唯一寫入咽喉點；補記寫 transactions 也在這裡。"""
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_

from models import CardCharge, MerchantBrand, Transaction

from . import hints, match as matcher
from .types import Charge, RecordResult, TxGroup, TxHint


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


def _no_merchant():
    return or_(CardCharge.merchant.is_(None), CardCharge.merchant == "")


def _by_ids(db, ids):
    return db.query(CardCharge).filter(CardCharge.id.in_(list(ids))).all() if ids else []


def set_merchant(db, mapping: dict[int, str]) -> None:
    for r in _by_ids(db, mapping):
        r.merchant = mapping[r.id]
    db.commit()


def missing_merchant_lines(db, message_id: str) -> set[int]:
    """該封信裡店名還空著的 line_no。"""
    rows = db.query(CardCharge.line_no).filter(CardCharge.message_id == message_id, _no_merchant()).all()
    return {n for (n,) in rows}


def set_merchant_by_line(db, message_id: str, mapping: dict[int, str]) -> int:
    """依 (信, 行號) 補店名；只寫店名還空著的列，已有的不動。回寫了幾筆。"""
    if not mapping:
        return 0
    n = 0
    for r in db.query(CardCharge).filter(CardCharge.message_id == message_id, _no_merchant()).all():
        name = mapping.get(r.line_no)
        if name and not r.merchant:
            r.merchant = name
            n += 1
    db.commit()
    return n


def missing_merchant(db) -> list[tuple[int, Charge]]:
    """店名還空著的刷卡（不分狀態），給 backfill 用收據補店名。"""
    rows = db.query(CardCharge).filter(_no_merchant()).order_by(CardCharge.charge_date, CardCharge.id).all()
    return [(r.id, _to_charge(r)) for r in rows]


def brand_map(db) -> dict[str, str]:
    return {raw: brand for raw, brand in db.query(MerchantBrand.raw, MerchantBrand.brand).all()}


def missing_brands(db) -> list[str]:
    """card_charges 裡出現、但 merchant_brands 還沒有的店名（去重、保持出現順序）。"""
    known = set(brand_map(db))
    seen: dict[str, None] = {}
    for (m,) in db.query(CardCharge.merchant).filter(CardCharge.merchant.isnot(None)).order_by(CardCharge.id).all():
        if m and m not in known:
            seen.setdefault(m)
    return list(seen)


def save_brands(db, mapping: dict[str, str]) -> int:
    """只存還沒有的原名（快取，不覆蓋）。回新增幾筆。"""
    known = set(brand_map(db))
    new = [(raw, b) for raw, b in mapping.items() if raw not in known]
    for raw, b in new:
        db.add(MerchantBrand(raw=raw, brand=b))
    db.commit()
    return len(new)


def branded(c: Charge, brands: dict[str, str]) -> Charge:
    """店名換成品牌（沒有對照就維持原名）；原名仍留在 card_charges.merchant。"""
    return replace(c, merchant=brands.get(c.merchant) or c.merchant)


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


def load_hints(db, since: date) -> list[TxHint]:
    """手記帳附上標籤，供找近似紀錄；載具發票與已被配走的紀錄不列。"""
    rows = [tuple(r) for r in (db.query(Transaction.id, Transaction.invoice_no, Transaction.created_at,
                                        Transaction.price, Transaction.item, Transaction.seller)
                               .filter(Transaction.created_at >= datetime.combine(since, time()),
                                       Transaction.invoice_no.is_(None))
                               .order_by(Transaction.id).all())]
    sellers: dict[str, str] = {}
    items: dict[str, str] = {}
    for tid, _, _, _, item, seller in rows:     # 只有手記帳（invoice_no 為 NULL），key 一律 id<id>
        key = f"id{tid}"
        if seller:
            sellers.setdefault(key, seller)
        if item:
            items.setdefault(key, item)
    labels = {k: sellers.get(k) or items.get(k) for k in items.keys() | sellers.keys()}
    used = used_group_keys(db)
    return [TxHint(g.key, g.tx_date, g.amount, labels.get(g.key))
            for g in matcher.group_transactions([r[:4] for r in rows]) if g.key not in used]


def all_charges(db) -> list[Charge]:
    return [_to_charge(r) for r in db.query(CardCharge).all()]


def unlist(db) -> int:
    """把已列進清單卡、但還沒處理的（unmatched）放回未列狀態，供重新分組再列。"""
    n = 0
    for r in db.query(CardCharge).filter(CardCharge.status == "unmatched", CardCharge.batch.isnot(None)).all():
        if r.status == "unmatched" and r.batch is not None:
            r.batch = None
            n += 1
    db.commit()
    return n


def assign_batch(db, ids: list[int], batch: str) -> None:
    for r in _by_ids(db, ids):
        r.batch = batch
    db.commit()


def _batch_rows(db, batch: str):
    return db.query(CardCharge).filter(CardCharge.batch == batch).order_by(CardCharge.charge_date, CardCharge.id).all()


def batch_items(db, batch: str) -> list[tuple[int, Charge, str]]:
    return [(r.id, _to_charge(r), r.status) for r in _batch_rows(db, batch)]


def batch_view(db, batch: str) -> tuple[str, list[tuple[int, Charge, str, str | None]]]:
    """該批所有列（各保留狀態）重算線索與分組；回 (多數列落在的組別 key, [(id, Charge, status, hint)])。"""
    rows = _batch_rows(db, batch)
    if not rows:
        return hints.GROUPS[-1][0], []
    status = {r.id: r.status for r in rows}
    brands = brand_map(db)
    items = [(r.id, branded(_to_charge(r), brands)) for r in rows]
    txs = load_hints(db, min(c.charge_date for _, c in items) - timedelta(days=1))
    arranged = hints.arrange(items, txs, all_charges(db))
    best = max(arranged, key=lambda g: len(g[1]))[0]       # max 取第一個最大 → 平手時 GROUPS 順序在前者
    return best, [(i, c, status[i], h) for _, grp in arranged for i, c, h in grp]


def ignore(db, batch: str, ids: list[int]) -> int:
    ids, n = set(ids), 0
    for r in _batch_rows(db, batch):
        if r.id in ids and r.status == "unmatched":
            r.status = "ignored"
            n += 1
    db.commit()
    return n


def transaction_fields(c: Charge, brands: dict[str, str] | None = None) -> dict:
    hh, mm = (int(x) for x in c.charge_time.split(":")) if c.charge_time else (12, 0)
    name = (brands or {}).get(c.merchant) or c.merchant
    return {"item": name or f"信用卡消費（{c.region}）", "price": c.amount, "source": "信用卡",
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
        brands = brand_map(db)
        recorded = total = 0
        for r in rows:
            if r.id in found:
                r.status, r.matched_key = "matched", found[r.id]
                continue
            tx = Transaction(**transaction_fields(_to_charge(r), brands))
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
