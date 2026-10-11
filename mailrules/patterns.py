"""主旨 → 樣式；寄件者網域與真人判斷（純函式）。"""
import re

from . import config
from .types import MailHeader

_PREFIX = re.compile(r"^\s*(?:re|fw|fwd|回覆|轉寄)\s*[:：]\s*", re.I)
_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")


def _domain_in(addr_domain: str, domains) -> bool:
    """網域相等或為其子網域。"""
    return any(addr_domain == d or addr_domain.endswith("." + d) for d in domains)


def addr_domain(addr: str) -> str:
    return addr.rpartition("@")[2].strip().lower()


def subject_pattern(subject: str, owner_name: str) -> str:
    s = subject or ""
    while True:
        t = _PREFIX.sub("", s, count=1)
        if t == s:
            break
        s = t
    if owner_name:
        s = re.sub(re.escape(owner_name), "〈本人〉", s, flags=re.I)
    s = _DIGITS.sub("#", s)
    s = _SPACES.sub(" ", s).strip()
    return s[:80]


def has_job_keyword(subject: str) -> bool:
    return bool(config.JOB_KEYWORDS.search(subject or ""))


def is_human(h: MailHeader) -> bool:
    if _domain_in(addr_domain(h.from_addr), config.JOB_BOARD_DOMAINS):
        return False
    local = h.from_addr.rpartition("@")[0]
    if config.SYSTEM_LOCALPART.search(local):
        return False
    return not h.unsub
