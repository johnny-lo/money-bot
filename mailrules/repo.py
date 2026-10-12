"""信件規則引擎的唯一 DB 存取層。JSON 欄位 labels_applied 更新一律指派新 list，SQLAlchemy 才偵測得到。"""
import re
from datetime import datetime

from models import MailMessage, MailRule, MailState, MailValuedDomain

from .types import Action, MailHeader, MessageState, Rule, Verdict

CARD_SIZE = 25
_IN_CHUNK = 500


def _now() -> datetime:
    return datetime.now()


def _rule(r) -> Rule:
    return Rule(id=r.id, sender=r.sender, subject_pattern=r.subject_pattern, category=r.category,
                status=r.status, suggested_by=r.suggested_by, card=r.card)


# ── 高水位 ─────────────────────────────────────────────────────────

def _state_row(db):
    return db.query(MailState).filter(MailState.id == 1).first()


def get_state(db):
    r = _state_row(db)
    if r is None or r.uidvalidity is None:
        return None
    return (r.uidvalidity, r.last_uid or 0, r.history_done_at)


def set_state(db, uidvalidity: int, last_uid: int) -> None:
    r = _state_row(db)
    if r is None:
        r = MailState(id=1)
        db.add(r)
    r.uidvalidity, r.last_uid = uidvalidity, last_uid
    db.commit()


def mark_history_done(db) -> None:
    r = _state_row(db)
    if r is None:
        r = MailState(id=1)
        db.add(r)
    r.history_done_at = _now()
    db.commit()


# ── 信件 ───────────────────────────────────────────────────────────

def upsert_headers(db, headers: list[MailHeader], owner: str) -> int:
    from .patterns import subject_pattern
    n = 0
    for i in range(0, len(headers), _IN_CHUNK):
        chunk = headers[i:i + _IN_CHUNK]
        rows = db.query(MailMessage).filter(MailMessage.gm_msgid.in_([h.gm_msgid for h in chunk])).all()
        have = {r.gm_msgid: r for r in rows}
        for h in chunk:
            r = have.get(h.gm_msgid)
            if r is None:
                db.add(MailMessage(gm_msgid=h.gm_msgid, uid=h.uid, from_addr=h.from_addr,
                                   subject_pattern=subject_pattern(h.subject, owner), subject=h.subject,
                                   sent_date=h.sent_date, in_inbox=h.in_inbox, labels_applied=[],
                                   protected=False))
                n += 1
            else:
                r.uid, r.in_inbox = h.uid, h.in_inbox
    db.commit()
    return n


def messages(db, include_trashed: bool = False) -> list:
    q = db.query(MailMessage)
    if not include_trashed:
        q = q.filter(MailMessage.trashed_at.is_(None))
    return q.order_by(MailMessage.id).all()


def headers(db) -> list[MailHeader]:
    """未丟垃圾桶的信。DB 不存 List-Unsubscribe，所以 unsub 一律 False（run 會用本次同步的信頭覆蓋）。"""
    return [MailHeader(gm_msgid=r.gm_msgid, uid=r.uid, from_addr=r.from_addr, from_name="",
                       subject=r.subject, sent_date=r.sent_date, labels=tuple(r.labels_applied or ()),
                       unsub=False, in_inbox=bool(r.in_inbox)) for r in messages(db)]


def states(db) -> dict[str, MessageState]:
    return {r.gm_msgid: MessageState(in_inbox=bool(r.in_inbox), labels_applied=frozenset(r.labels_applied or ()),
                                     trashed=r.trashed_at is not None) for r in messages(db, include_trashed=True)}


def save_verdicts(db, verdicts: dict[str, Verdict]) -> None:
    ids = list(verdicts)
    for i in range(0, len(ids), _IN_CHUNK):
        rows = db.query(MailMessage).filter(MailMessage.gm_msgid.in_(ids[i:i + _IN_CHUNK])).all()
        for r in rows:
            v = verdicts.get(r.gm_msgid)
            if v is not None:
                r.category, r.reason, r.protected = v.category, v.reason, v.protected
    db.commit()


def record_actions(db, done: list[Action]) -> None:
    if not done:
        return
    ids = {a.gm_msgid for a in done}
    by = {r.gm_msgid: r for r in db.query(MailMessage).filter(MailMessage.gm_msgid.in_(list(ids))).all()
          if r.gm_msgid in ids}
    for a in done:
        r = by.get(a.gm_msgid)
        if r is None:
            continue
        if a.kind == "label" and a.label:
            cur = list(r.labels_applied or [])
            if a.label not in cur:
                r.labels_applied = cur + [a.label]
        elif a.kind == "archive":
            r.in_inbox = False
        elif a.kind == "trash":
            r.trashed_at = _now()
    db.commit()


# ── 規則 ───────────────────────────────────────────────────────────

def confirmed_rules(db) -> list[Rule]:
    return [_rule(r) for r in db.query(MailRule).filter(MailRule.status == "confirmed").order_by(MailRule.id).all()]


def known_keys(db) -> set[tuple[str, str]]:
    return {(r.sender, r.subject_pattern) for r in db.query(MailRule).all()}


def _max_card_no(db) -> int:
    best = 0
    for r in db.query(MailRule).filter(MailRule.card.isnot(None)).all():
        m = re.fullmatch(r"s(\d+)", r.card or "")
        if m:
            best = max(best, int(m.group(1)))
    return best


def add_suggestions(db, items: list[tuple[str, str, str, str]]) -> list[str]:
    seen, uniq = set(), []
    for it in items:
        if (it[0], it[1]) not in seen:
            seen.add((it[0], it[1]))
            uniq.append(it)
    n, cards = _max_card_no(db), []
    for i in range(0, len(uniq), CARD_SIZE):
        n += 1
        card = f"s{n}"
        cards.append(card)
        for sender, pattern, category, by in uniq[i:i + CARD_SIZE]:
            db.add(MailRule(sender=sender, subject_pattern=pattern, category=category,
                            status="suggested", suggested_by=by, card=card))
    if cards:
        db.commit()
    return cards


def _card_rows(db, card: str) -> list:
    return db.query(MailRule).filter(MailRule.card == card).order_by(MailRule.id).all()


def card_rules(db, card: str) -> list[Rule]:
    return [_rule(r) for r in _card_rows(db, card)]


def confirm_card(db, card: str, rejected_ids: list[int]) -> tuple[int, int]:
    rej, confirmed, rejected = set(rejected_ids), 0, 0
    for r in _card_rows(db, card):
        if r.status != "suggested":
            continue
        if r.id in rej:
            r.status = "rejected"
            rejected += 1
        else:
            r.status, r.confirmed_at = "confirmed", _now()
            confirmed += 1
    db.commit()
    return confirmed, rejected


def reject(db, card: str, ids: list[int]) -> int:
    want, n = set(ids), 0
    for r in _card_rows(db, card):
        if r.status == "suggested" and r.id in want:
            r.status = "rejected"
            n += 1
    db.commit()
    return n


def rejected_rules(db) -> list[Rule]:
    return [_rule(r) for r in db.query(MailRule).filter(MailRule.status == "rejected").order_by(MailRule.id).all()]


def assign(db, rule_id: int, category: str) -> None:
    r = db.query(MailRule).filter(MailRule.id == rule_id).first()
    if r is None:
        return
    r.category, r.status, r.suggested_by, r.confirmed_at = category, "confirmed", "user", _now()
    db.commit()


def pending_cards(db) -> list[str]:
    cards = {r.card for r in db.query(MailRule).filter(MailRule.status == "suggested").all() if r.card}
    return sorted(cards, key=lambda c: int(c[1:]) if c[1:].isdigit() else 0)


# ── 重視網域 ───────────────────────────────────────────────────────

def add_valued(db, domains: dict[str, str]) -> None:
    if not domains:
        return
    have = valued(db)
    new = [MailValuedDomain(domain=d, source_subject_pattern=p) for d, p in domains.items() if d not in have]
    for r in new:
        db.add(r)
    if new:
        db.commit()


def valued(db) -> set[str]:
    return {r.domain for r in db.query(MailValuedDomain).all()}


def valued_set(db) -> set[str]:
    return valued(db)
