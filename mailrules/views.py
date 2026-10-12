"""名單檢視：每一層（保護層、規則、未知、各類別、垃圾桶）現在有哪些信／規則。

只讀 mail_messages / mail_rules / mail_valued_domains，不寫 DB、不連 Gmail。
build_layer / overview_from 是純函式（輸入都是 dict 列）；load / overview / layer 是讀 DB 的薄包裝。
Discord `/信件名單` 與 PWA 📬 分頁（routes/mail.py）共用同一組函式。
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from database import SessionLocal
from models import MailMessage, MailRule, MailValuedDomain

from . import config
from .classify import REASON_HUMAN, REASON_JOB, REASON_VALUED
from .patterns import _domain_in, addr_domain
from .plan import next_step
from .types import MessageState

TRASH_RECOVER_DAYS = 30        # Gmail 垃圾桶 30 天後永久刪除

_PROTECT_REASONS = (REASON_JOB, REASON_VALUED, REASON_HUMAN)
_STATUS = {"suggested": "待確認", "confirmed": "已確認", "rejected": "已拒絕"}
_STATUS_ORDER = {"suggested": 0, "confirmed": 1, "rejected": 2}
_BY = {"builtin": "內建", "ai": "AI", "user": "你"}
_STEP = {"archive": "移出", "trash": "丟"}

LAYERS: list[tuple[str, str]] = (
    [("job", "🛡 求職字眼"), ("valued", "🛡 重視的公司"), ("human", "🛡 真人來信"),
     ("self", "寄給自己"), ("rules", "你的規則"), ("unknown", "未知")]
    + [(k, name) for k, name in config.CATEGORIES if k not in ("keep_inbox", "self")]
    + [("trash", "🗑 30 天內丟的")]
)
_TITLES = dict(LAYERS)
_CAT_ORDER = {k: i for i, (k, _) in enumerate(config.CATEGORIES)}


def _ymd(d) -> str | None:
    return d.strftime("%Y-%m-%d") if d else None


def _short(d: date, today: date) -> str:
    return d.strftime("%m/%d") if d.year == today.year else d.strftime("%Y/%m/%d")


def _day(v) -> date | None:
    return v.date() if isinstance(v, datetime) else v


def _where(m: dict) -> str:
    if m.get("trashed_at"):
        return "垃圾桶"
    if m.get("in_inbox"):
        return "收件匣"
    if m.get("labels_applied"):
        return "資料夾"
    return "已移出"


def _next(m: dict, key: str, today: date) -> str | None:
    if key == "trash":
        t = _day(m.get("trashed_at"))
        return f"{_short(t + timedelta(days=TRASH_RECOVER_DAYS), today)} 前救得回" if t else None
    st = MessageState(in_inbox=bool(m.get("in_inbox")), labels_applied=frozenset(m.get("labels_applied") or ()),
                      trashed=bool(m.get("trashed_at")))
    step = next_step(m.get("category"), _day(m.get("sent_date")), st)
    return f"{_short(step[1], today)} {_STEP[step[0]]}" if step else None


def _message_row(m: dict, key: str, today: date) -> dict:
    return {"date": _ymd(m.get("sent_date")), "sender": m["from_addr"], "subject": m["subject"],
            "where": _where(m), "next": _next(m, key, today)}


def _match_msg(m: dict, key: str, today: date) -> bool:
    live = not m.get("trashed_at")
    reason = m.get("reason")
    if key == "job":
        return live and reason == REASON_JOB
    if key == "human":
        return live and reason == REASON_HUMAN
    if key == "self":
        return live and m.get("category") == "self"
    if key == "unknown":
        return live and m.get("category") is None
    if key == "trash":
        t = _day(m.get("trashed_at"))
        return t is not None and t >= today - timedelta(days=TRASH_RECOVER_DAYS)
    return live and m.get("category") == key and reason not in _PROTECT_REASONS


def _hit(q: str, *fields) -> bool:
    return not q or any(q in (f or "").lower() for f in fields)


def build_layer(key, msgs, rules, domains, today, q="", offset=0, limit=200) -> dict:
    if key not in _TITLES:
        raise KeyError(key)
    kind, items = _collect(key, msgs, rules, domains, today, (q or "").strip().lower())
    start = max(0, offset)
    page = items[start:start + max(0, limit)]
    if kind == "messages":
        rows = [_message_row(m, key, today) for m in page]
    elif kind == "rules":
        rows = [{"sender": r["sender"], "pattern": r["subject_pattern"],
                 "category": config.LABELS.get(r["category"], r["category"]),
                 "status": _STATUS.get(r["status"], r["status"]), "by": _BY.get(r["suggested_by"], r["suggested_by"])}
                for r in page]
    else:
        rows = page
    return {"key": key, "title": _TITLES[key], "kind": kind, "total": len(items), "rows": rows}


def _collect(key, msgs, rules, domains, today, q) -> tuple[str, list]:
    """該層符合條件（含搜尋）的完整、已排序的項目；messages / rules 是原始 dict，其餘已是輸出列。"""
    if key == "rules":
        items = [r for r in rules if _hit(q, r["sender"], r["subject_pattern"])]
        items.sort(key=lambda r: (_STATUS_ORDER.get(r["status"], 9), _CAT_ORDER.get(r["category"], 99),
                                  r["sender"], r["subject_pattern"]))
        return "rules", items
    if key == "valued":
        out = []
        valued_doms = [addr_domain(m["from_addr"]) for m in msgs if m.get("reason") == REASON_VALUED]
        for d in domains:
            dom = (d["domain"] or "").lower()
            if not _hit(q, dom):
                continue
            n = sum(1 for md in valued_doms if _domain_in(md, [dom]))
            out.append({"domain": d["domain"], "since": _ymd(d.get("first_seen")),
                        "pattern": d.get("source_subject_pattern"), "count": n})
        out.sort(key=lambda r: (-r["count"], r["domain"]))
        return "domains", out
    hits = [m for m in msgs if _match_msg(m, key, today)]
    if key == "unknown":
        groups: dict = defaultdict(lambda: [0, None])
        for m in hits:
            g = groups[(m["from_addr"], m["subject_pattern"])]
            g[0] += 1
            d = _day(m.get("sent_date"))
            if d and (g[1] is None or d > g[1]):
                g[1] = d
        out = [{"sender": s, "pattern": p, "count": n, "last": _ymd(last)}
               for (s, p), (n, last) in groups.items() if _hit(q, s, p)]
        out.sort(key=lambda r: (-r["count"], r["sender"], r["pattern"]))
        return "groups", out
    hits = [m for m in hits if _hit(q, m["from_addr"], m["subject"])]
    hits.sort(key=lambda m: _day(m.get("sent_date")) or date.min, reverse=True)
    return "messages", hits


def overview_from(msgs, rules, domains, today) -> list[dict]:
    out = []
    for key, title in LAYERS:
        _, items = _collect(key, msgs, rules, domains, today, "")
        out.append({"key": key, "title": title, "count": len(items)})
    return out


def load(db) -> tuple[list[dict], list[dict], list[dict]]:
    """三張表各讀一次轉成 dict 列（約一萬列，整包讀進來再交給純函式）。"""
    mc = ("from_addr", "subject", "subject_pattern", "sent_date", "category", "reason", "in_inbox",
          "labels_applied", "trashed_at")
    msgs = [dict(zip(mc, r)) for r in db.query(*[getattr(MailMessage, c) for c in mc]).all()]
    rc = ("sender", "subject_pattern", "category", "status", "suggested_by")
    rules = [dict(zip(rc, r)) for r in db.query(*[getattr(MailRule, c) for c in rc]).all()]
    dc = ("domain", "first_seen", "source_subject_pattern")
    domains = [dict(zip(dc, r)) for r in db.query(*[getattr(MailValuedDomain, c) for c in dc]).all()]
    return msgs, rules, domains


def _with_db(db, fn):
    if db is not None:
        return fn(db)
    s = SessionLocal()
    try:
        return fn(s)
    finally:
        s.close()


def overview(db, today: date) -> list[dict]:
    return _with_db(db, lambda s: overview_from(*load(s), today))


def layer(db, key: str, today: date, q: str = "", offset: int = 0, limit: int = 200) -> dict:
    if key not in _TITLES:
        raise KeyError(key)
    return _with_db(db, lambda s: build_layer(key, *load(s), today, q=q, offset=offset, limit=limit))
