"""保留期限表 → 今天該做的動作（純函式，冪等靠 MessageState）。"""
from datetime import date

from . import config
from .patterns import addr_domain
from .types import Action, MailHeader, MessageState, Verdict


def school_label(from_addr: str) -> str:
    base = config.RETENTION["school"].label
    parts = addr_domain(from_addr).split(".")
    if "edu" in parts:
        i = parts.index("edu")
        if i >= 1 and parts[i - 1]:
            return f"{base}/{parts[i - 1]}"
    return base


def plan_actions(h: MailHeader, v: Verdict, st: MessageState, today: date, mode: str) -> list[Action]:
    cat = v.category
    if cat is None or v.protected or st.trashed or cat not in config.RETENTION:
        return []
    r = config.RETENTION[cat]
    age = (today - h.sent_date).days if h.sent_date else 0
    out: list[Action] = []
    lab = school_label(h.from_addr) if cat == "school" else r.label
    if lab and lab not in st.labels_applied:
        out.append(Action(h.gm_msgid, h.uid, "label", lab))
    trash_days = 0 if (mode == "history" and cat == "promo") else r.trash_after_days
    if trash_days is not None and age >= trash_days:
        out.append(Action(h.gm_msgid, h.uid, "trash"))
    elif r.archive_after_days is not None and age >= r.archive_after_days and st.in_inbox:
        out.append(Action(h.gm_msgid, h.uid, "archive"))
    return out
