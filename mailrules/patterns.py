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


def has_strong_job_keyword(subject: str) -> bool:
    return bool(config.STRONG_JOB_KEYWORDS.search(subject or ""))


def is_school(domain: str) -> bool:
    return any(domain.endswith(s) for s in config.SCHOOL_SUFFIXES)


def count_by_domain(addrs, domains) -> dict[str, int]:
    """{網域: 封數}：每個網域（含子網域）有幾個寄件地址；0 封的不列。確認卡與名單共用，數字才會一致。"""
    doms = {(d or "").lower() for d in domains}
    out: dict[str, int] = {}
    for a in addrs:
        ad = addr_domain(a or "")
        for d in doms:
            if d and _domain_in(ad, [d]):
                out[d] = out.get(d, 0) + 1
    return out


# 「名.姓」：兩到三段英文字（每段至少 2 個字母，以 . _ - 連接），最後一段可帶數字結尾
_NAME_LOCAL = re.compile(r"[a-z]{2,}(?:[._-][a-z]{2,}){1,2}\d*", re.I)


def is_human(h: MailHeader) -> bool:
    """免費信箱（不像系統代號）→ 真人；其他網域只認「名.姓」，而且沒有任何一段就是網域裡的品牌。
    試跑時郵局、券商、銀行、公司系統帳號都被當成真人，所以收緊。"""
    addr = (h.from_addr or "").strip().lower()
    local, _, dom = addr.rpartition("@")
    if not local or not dom:
        return False
    if _domain_in(dom, config.JOB_BOARD_DOMAINS) or h.unsub or config.SYSTEM_LOCALPART.search(local):
        return False
    if _domain_in(dom, config.FREEMAIL_DOMAINS):
        return True
    if not _NAME_LOCAL.fullmatch(local):
        return False
    parts = {p.rstrip("0123456789") for p in re.split(r"[._-]", local)}
    labels = set(re.split(r"[.-]", dom))
    return not parts & labels
