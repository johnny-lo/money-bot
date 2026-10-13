"""信件規則引擎的唯一 DB 存取層。JSON 欄位 labels_applied 更新一律指派新 list，SQLAlchemy 才偵測得到。"""
import hashlib
import re
from datetime import datetime

from models import MailMessage, MailRule, MailState, MailValuedDomain

from . import config
from .types import Action, MailHeader, MessageState, Rule, ValuedDomain, Verdict

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


def plan_posted_card(db) -> str | None:
    """上次成功發出的歷史計畫卡是哪一套已確認規則（rules_fingerprint）；None＝沒成功發過。"""
    r = _state_row(db)
    return None if r is None else r.plan_posted_card


def set_plan_posted(db, fingerprint: str) -> None:
    """只在計畫卡真的送出（post_sync_wait 回 True）後呼叫。"""
    r = _state_row(db)
    if r is None:
        r = MailState(id=1)
        db.add(r)
    r.plan_posted_card = fingerprint
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
                                   protected=False, unsub=bool(h.unsub), from_name=h.from_name or None))
                n += 1
            else:
                r.uid, r.in_inbox = h.uid, h.in_inbox
                r.unsub, r.from_name = bool(h.unsub), h.from_name or None
                r.gone_at = None                           # 又同步得到 → 信還在
    db.commit()
    return n


def messages(db, include_trashed: bool = False) -> list:
    """已不在信箱（gone_at）的信一律不列：不再規劃、不再分類。"""
    q = db.query(MailMessage).filter(MailMessage.gone_at.is_(None))
    if not include_trashed:
        q = q.filter(MailMessage.trashed_at.is_(None))
    return q.order_by(MailMessage.id).all()


def headers(db) -> list[MailHeader]:
    """未丟垃圾桶、還在信箱的信；unsub / 顯示名稱從 DB 讀回（不是本次同步的電子報才不會被當成真人寄的）。"""
    return [MailHeader(gm_msgid=r.gm_msgid, uid=r.uid, from_addr=r.from_addr, from_name=r.from_name or "",
                       subject=r.subject, sent_date=r.sent_date, labels=tuple(r.labels_applied or ()),
                       unsub=bool(r.unsub), in_inbox=bool(r.in_inbox)) for r in messages(db)]


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
        r.uid = a.uid                                      # apply 可能用 X-GM-MSGID 找到新 uid
        if a.kind == "label" and a.label:
            cur = list(r.labels_applied or [])
            if a.label not in cur:
                r.labels_applied = cur + [a.label]
        elif a.kind == "archive":
            r.in_inbox = False
        elif a.kind == "trash":
            r.trashed_at = _now()
    db.commit()


def mark_gone(db, gm_msgids: list[str]) -> None:
    """所有郵件已找不到的信：記 gone_at，之後不再規劃、不算失敗、名單不列。"""
    ids = set(gm_msgids)
    if not ids:
        return
    now, ids_l = _now(), sorted(ids)
    for i in range(0, len(ids_l), _IN_CHUNK):
        for r in db.query(MailMessage).filter(MailMessage.gm_msgid.in_(ids_l[i:i + _IN_CHUNK])).all():
            if r.gm_msgid in ids and r.gone_at is None:
                r.gone_at = now
    db.commit()


# ── 規則 ───────────────────────────────────────────────────────────

def confirmed_rules(db) -> list[Rule]:
    return [_rule(r) for r in db.query(MailRule).filter(MailRule.status == "confirmed").order_by(MailRule.id).all()]


def rules_fingerprint(rules: list[Rule]) -> str:
    """已確認規則集合的指紋（每條的 id／寄件者／樣式／類別）：計畫卡核可的是哪一套規則。
    確認一張卡、手動指定一條規則都會讓它變；拒絕、長出新的未確認卡不會。"""
    key = "\n".join(f"{r.id}|{r.sender}|{r.subject_pattern}|{r.category}"
                    for r in sorted(rules, key=lambda r: (r.id or 0, r.sender, r.subject_pattern)))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def plan_fingerprint(rules: list[Rule], valued: set[str]) -> str:
    """計畫卡核可的是哪一套「已確認規則＋已確認重視網域」。沒有已確認網域時等於 rules_fingerprint
    （升級前發出的計畫卡不會因此過期）。確認網域會讓它變；新增待確認網域、拒絕網域不會。"""
    if not valued:
        return rules_fingerprint(rules)
    key = rules_fingerprint(rules) + "\nvalued:" + ",".join(sorted(valued))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def confirmed_fingerprint(db) -> str:
    return plan_fingerprint(confirmed_rules(db), valued_set(db))


def known_keys(db) -> set[tuple[str, str]]:
    return {(r.sender, r.subject_pattern) for r in db.query(MailRule).all()}


def _max_card_no(db) -> int:
    best = 0
    for r in db.query(MailRule).filter(MailRule.card.isnot(None)).all():
        m = re.fullmatch(r"s(\d+)", r.card or "")
        if m:
            best = max(best, int(m.group(1)))
    return best


def max_card(db) -> str | None:
    """目前最大的確認卡號（'s7'）；從沒開過卡回 None。"""
    n = _max_card_no(db)
    return f"s{n}" if n else None


def card_no(card: str | None) -> int:
    """'s7' → 7；'none'／None／壞值 → 0。"""
    m = re.fullmatch(r"s(\d+)", card or "")
    return int(m.group(1)) if m else 0


_CAT_ORDER = {k: i for i, (k, _) in enumerate(config.CATEGORIES)}


def add_suggestions(db, items: list[tuple[str, str, str, str]]) -> list[str]:
    """每類一張整批核可卡：同一次呼叫裡同一個類別的所有建議放同一張卡（依類別順序開卡）；卡號只增不減、不重用。"""
    seen, uniq = set(), []
    for it in items:
        if (it[0], it[1]) not in seen:
            seen.add((it[0], it[1]))
            uniq.append(it)
    uniq.sort(key=lambda it: (_CAT_ORDER.get(it[2], len(_CAT_ORDER)), it[2], it[0], it[1]))
    groups: dict[str, list] = {}
    for it in uniq:
        groups.setdefault(it[2], []).append(it)
    n, cards = _max_card_no(db), []
    for group in groups.values():
        n += 1
        card = f"s{n}"
        cards.append(card)
        for sender, pattern, category, by in group:
            db.add(MailRule(sender=sender, subject_pattern=pattern, category=category,
                            status="suggested", suggested_by=by, card=card))
    if cards:
        db.commit()
    return cards


def _card_rows(db, card: str) -> list:
    return db.query(MailRule).filter(MailRule.card == card).order_by(MailRule.id).all()


def card_rules(db, card: str) -> list[Rule]:
    return [_rule(r) for r in _card_rows(db, card)]


def card_counts(db, card: str) -> dict[tuple[str, str], int]:
    """{(sender, pattern): 封數}：卡上每個樣式現在還在信箱的信有幾封（確認卡顯示用）。"""
    keys = {(r.sender, r.subject_pattern) for r in _card_rows(db, card)}
    senders = sorted({s for s, _ in keys})
    out: dict = {}
    for i in range(0, len(senders), _IN_CHUNK):
        rows = (db.query(MailMessage)
                .filter(MailMessage.from_addr.in_(senders[i:i + _IN_CHUNK]), MailMessage.gone_at.is_(None)).all())
        for r in rows:
            k = (r.from_addr, r.subject_pattern)
            if k in keys and r.gone_at is None:
                out[k] = out.get(k, 0) + 1
    return out


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


def reject_senders(db, card: str, senders: list[str]) -> int:
    """整批核可卡的「這些不是」：這些寄件者在這張卡上還在待確認的規則全部拒絕；回傳拒絕了幾條。"""
    want, n = set(senders), 0
    for r in _card_rows(db, card):
        if r.card == card and r.status == "suggested" and r.sender in want:
            r.status = "rejected"
            n += 1
    db.commit()
    return n


def assign_sender(db, card: str, sender: str, category: str) -> int:
    """被拒絕的寄件者手動指定類別：這個寄件者在這張卡上被拒絕的規則（含先前手動指定過的，選錯可重選）
    一起改成該類別並確認；回傳改了幾條。"""
    n, now = 0, _now()
    for r in _card_rows(db, card):
        if r.card != card or r.sender != sender:
            continue
        if r.status == "rejected" or (r.status == "confirmed" and r.suggested_by == "user"):
            r.category, r.status, r.suggested_by, r.confirmed_at = category, "confirmed", "user", now
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


def unposted_cards(db) -> list[str]:
    """待確認、而且從沒成功發到 Discord 的卡（頻道沒設、bot 沒 ready、發送失敗）：下次要完整發。"""
    rows = [r for r in db.query(MailRule).filter(MailRule.status == "suggested").all()
            if r.status == "suggested" and r.card]
    posted = {r.card for r in rows if r.posted_at is not None}
    return sorted({r.card for r in rows} - posted, key=card_no)


def mark_cards_posted(db, cards: list[str]) -> None:
    """只在卡真的送出（post_sync_wait 回 True）後呼叫；整張卡的每一列都記。"""
    want = set(cards)
    if not want:
        return
    now = _now()
    for r in db.query(MailRule).filter(MailRule.card.in_(sorted(want))).all():
        if r.card in want and r.posted_at is None:
            r.posted_at = now
    db.commit()


# ── 重視網域 ───────────────────────────────────────────────────────
# 新學到的一律 pending，分到重視公司確認卡（v<N>，只增不減、和規則確認卡 s<N> 各自獨立）；
# 只有 confirmed 會保護信（valued_set）；rejected 的網域留在表裡，永遠不再學、不重開。

VALUED_CARD_SIZE = 20


def _vd(r) -> ValuedDomain:
    return ValuedDomain(domain=r.domain, pattern=r.source_subject_pattern, status=r.status, card=r.card)


def valued_card_no(card: str | None) -> int:
    """'v7' → 7；None／壞值 → 0。"""
    m = re.fullmatch(r"v(\d+)", card or "")
    return int(m.group(1)) if m else 0


def _valued_rows(db) -> list:
    return db.query(MailValuedDomain).all()


def add_valued(db, domains: dict[str, str]) -> list[str]:
    """domains＝這次（從所有還在信箱的信）學到的 {網域: 主旨樣式}。只新增表裡完全沒有的網域，一律 pending、
    每 VALUED_CARD_SIZE 個一張卡；回傳新開的卡號。
    沒卡號的 pending 列是舊版規則學的（欄位 migration 補成 pending）：這次還學得到的補上卡，學不到的刪掉
    （當初是弱字眼學的，從沒生效、也沒給本人看過）。"""
    rows = _valued_rows(db)
    have = {r.domain for r in rows}
    legacy = [r for r in rows if r.card is None and r.status == "pending"]
    changed = False
    for r in legacy:
        if r.domain not in domains:
            db.delete(r)
            changed = True
    todo = sorted([(d, p, None) for d, p in domains.items() if d not in have]
                  + [(r.domain, r.source_subject_pattern, r) for r in legacy if r.domain in domains],
                  key=lambda t: t[0])
    n = max((valued_card_no(r.card) for r in rows), default=0)
    cards = []
    for i in range(0, len(todo), VALUED_CARD_SIZE):
        n += 1
        card = f"v{n}"
        cards.append(card)
        for d, p, r in todo[i:i + VALUED_CARD_SIZE]:
            if r is None:
                db.add(MailValuedDomain(domain=d, source_subject_pattern=p, status="pending", card=card))
            else:
                r.card = card
    if cards or changed:
        db.commit()
    return cards


def valued(db) -> set[str]:
    """表裡所有網域（任何狀態）。"""
    return {r.domain for r in _valued_rows(db)}


def valued_set(db) -> set[str]:
    """只有本人確認過的網域會保護信。"""
    return {r.domain for r in db.query(MailValuedDomain).filter(MailValuedDomain.status == "confirmed").all()
            if r.status == "confirmed"}


def pending_valued_count(db) -> int:
    return sum(1 for r in db.query(MailValuedDomain).filter(MailValuedDomain.status == "pending").all()
               if r.status == "pending")


def _valued_card_rows(db, card: str) -> list:
    rows = db.query(MailValuedDomain).filter(MailValuedDomain.card == card).order_by(MailValuedDomain.domain).all()
    return sorted((r for r in rows if r.card == card), key=lambda r: r.domain)


def valued_card(db, card: str) -> list[ValuedDomain]:
    return [_vd(r) for r in _valued_card_rows(db, card)]


def valued_card_counts(db, card: str) -> dict[str, int]:
    """{網域: 封數}：卡上每個網域（含子網域）現在還在信箱（沒丟、沒消失）、沒有退訂連結的信有幾封
    ＝確認後會被保護的數量（群發信不保護）。確認卡顯示用。"""
    from .patterns import count_by_domain
    doms = [r.domain for r in _valued_card_rows(db, card)]
    if not doms:
        return {}
    rows = (db.query(MailMessage)
            .filter(MailMessage.gone_at.is_(None), MailMessage.trashed_at.is_(None), MailMessage.unsub.is_(False))
            .all())
    return count_by_domain([r.from_addr for r in rows if r.gone_at is None and r.trashed_at is None and not r.unsub],
                           doms)


def pending_valued_cards(db) -> list[str]:
    """還有待確認網域的重視公司卡。"""
    rows = db.query(MailValuedDomain).filter(MailValuedDomain.status == "pending").all()
    return sorted({r.card for r in rows if r.status == "pending" and r.card}, key=valued_card_no)


def unposted_valued_cards(db) -> list[str]:
    """還有待確認網域、而且從沒成功發到 Discord 的重視公司卡：下次要完整發。"""
    rows = [r for r in db.query(MailValuedDomain).filter(MailValuedDomain.status == "pending").all()
            if r.status == "pending" and r.card]
    posted = {r.card for r in rows if r.posted_at is not None}
    return sorted({r.card for r in rows} - posted, key=valued_card_no)


def mark_valued_posted(db, cards: list[str]) -> None:
    """只在卡真的送出（post_sync_wait 回 True）後呼叫；整張卡的每一列都記。"""
    want = set(cards)
    if not want:
        return
    now = _now()
    for r in db.query(MailValuedDomain).filter(MailValuedDomain.card.in_(sorted(want))).all():
        if r.card in want and r.posted_at is None:
            r.posted_at = now
    db.commit()


def reject_valued(db, card: str, domains: list[str]) -> int:
    """拒絕某張卡上指定的（還在待確認的）網域；回傳拒絕了幾個。"""
    want, n, now = set(domains), 0, _now()
    for r in _valued_card_rows(db, card):
        if r.status == "pending" and r.domain in want:
            r.status, r.decided_at = "rejected", now
            n += 1
    db.commit()
    return n


def confirm_valued_card(db, card: str) -> int:
    """卡上仍待確認的網域全部確認；回傳確認了幾個。"""
    n, now = 0, _now()
    for r in _valued_card_rows(db, card):
        if r.status == "pending":
            r.status, r.decided_at = "confirmed", now
            n += 1
    db.commit()
    return n
