"""保留期限表 → 今天該做的動作（純函式，冪等靠 MessageState）。"""
from datetime import date, timedelta

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
    if cat is None or st.trashed or cat not in config.RETENTION:
        return []
    r = config.RETENTION[cat]
    age = (today - h.sent_date).days if h.sent_date else 0
    out: list[Action] = []
    lab = school_label(h.from_addr) if cat == "school" else r.label
    if lab and lab not in st.labels_applied:
        out.append(Action(h.gm_msgid, h.uid, "label", lab))
    if v.protected:                       # 安全網命中：最多加標籤，任何模式都不移出、不丟
        return out
    trash_days = 0 if (mode == "history" and cat == "promo") else r.trash_after_days
    if trash_days is not None and age >= trash_days:
        out.append(Action(h.gm_msgid, h.uid, "trash"))
    elif r.archive_after_days is not None and age >= r.archive_after_days and st.in_inbox:
        out.append(Action(h.gm_msgid, h.uid, "archive"))
    return out


def next_step(category: str | None, sent_date: date | None, st: MessageState,
              today: date | None = None) -> tuple[str, date] | None:
    """這封信接下來（每日模式）最早會被做什麼、哪天做；沒有下一步回 None。只給名單檢視顯示用。

    帶 today 時，丟的期限已到就直接回丟（和 plan_actions 每日模式「trash 優先」一致）。"""
    r = config.RETENTION.get(category) if category else None
    if r is None or sent_date is None or st.trashed:
        return None
    arch, trash = r.archive_after_days, r.trash_after_days
    if today is not None and trash is not None and (today - sent_date).days >= trash:
        return "trash", sent_date + timedelta(days=trash)
    if st.in_inbox and arch is not None and (trash is None or arch < trash):
        return "archive", sent_date + timedelta(days=arch)
    if trash is not None:
        return "trash", sent_date + timedelta(days=trash)
    return None
