"""分類：安全網 → 本人確認規則 → 內建建議（純函式）。"""
import re

from . import config
from .patterns import _domain_in, addr_domain, has_job_keyword, is_human, subject_pattern
from .types import MailHeader, Rule, Verdict

__all__ = ["has_job_keyword", "is_human", "learn_valued_domains", "match_rule", "classify", "builtin_suggest"]


def learn_valued_domains(headers: list[MailHeader], self_addrs: set[str], company_domains: set[str]) -> dict[str, str]:
    self_domains = {addr_domain(a) for a in self_addrs}
    out: dict[str, str] = {}
    for h in headers:
        if not has_job_keyword(h.subject):
            continue
        d = addr_domain(h.from_addr)
        if not d or d in out:
            continue
        if (_domain_in(d, config.JOB_BOARD_DOMAINS) or _domain_in(d, config.FREEMAIL_DOMAINS)
                or d in self_domains or _domain_in(d, company_domains)):
            continue
        out[d] = subject_pattern(h.subject, "")
    return out


def match_rule(h: MailHeader, pattern: str, rules: list[Rule]) -> Rule | None:
    addr = h.from_addr.lower()
    dom = addr_domain(addr)
    best, best_rank = None, -1
    for r in rules:
        if r.status != "confirmed":
            continue
        sender = (r.sender or "").lower()
        if sender.startswith("@"):
            if not _domain_in(dom, [sender[1:]]):
                continue
            base = 0
        elif sender == addr:
            base = 2
        else:
            continue
        if r.subject_pattern == pattern:
            rank = base + 1
        elif r.subject_pattern == "*":
            rank = base
        else:
            continue
        if rank > best_rank:
            best, best_rank = r, rank
    return best


def classify(h: MailHeader, pattern: str, rules: list[Rule], valued: set[str], self_addrs: set[str]) -> Verdict:
    if has_job_keyword(h.subject):
        return Verdict("keep_inbox", "主旨有求職字眼", True)
    r = match_rule(h, pattern, rules)
    if _domain_in(addr_domain(h.from_addr), valued):
        if r and r.sender.lower() == h.from_addr.lower():
            return Verdict(r.category, f"規則 #{r.id}", False)
        return Verdict("keep_inbox", "重視的公司", True)
    if h.from_addr in self_addrs:
        return Verdict(r.category if r else "self", "寄給自己", False)
    if r:
        return Verdict(r.category, f"規則 #{r.id}", False)
    if is_human(h):
        return Verdict("keep_inbox", "像真人寄的", True)
    return Verdict(None, "未知", False)


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


_SECURITY = _rx(r"陌生|異常|可疑|安全性快訊|安全性警示|新裝置|security alert")
_LOGIN = _rx(r"登入|login|sign.?in|驗證碼|認證碼|OTP|verification code")
_JOB_104 = _rx(r"職務|職缺")
_JOB_ALERT = _rx(r"this job is a match|job alert")
_TAX = _rx(r"薪資|扣繳|所得稅|保單|保費|保險契約|稅|健保|勞保")
_CARD = _rx(r"消費通知|交易.*通知|扣款|轉帳|繳款|繳費|入帳")
_BILL = _rx(r"帳單|對帳單|statement")
_RECEIPT = _rx(r"收據|receipt|訂單|order|出貨|配送|已送達|發票|invoice")
_TRAVEL = _rx(r"航班|班機|機票|訂房|booking|itinerary|行程|登機")
_PROMO = _rx(r"電子報|優惠|折扣|抽獎|限時|週年慶|回饋|newsletter")


def builtin_suggest(h: MailHeader, pattern: str, company_domains: set[str]) -> str | None:
    s = h.subject or ""
    dom = addr_domain(h.from_addr)
    local = h.from_addr.rpartition("@")[0].lower()
    linkedin = _domain_in(dom, ["linkedin.com"])
    if _SECURITY.search(s):
        return "security"
    if _LOGIN.search(s):
        return "login"
    if ((linkedin and ("jobalerts" in local or "jobs" in local))
            or (_domain_in(dom, ["104.com.tw"]) and _JOB_104.search(s))
            or _JOB_ALERT.search(s)):
        return "jobs"
    if linkedin:
        return "social"
    if dom.endswith(".edu.tw") or dom.endswith(".edu"):
        return "school"
    if _TAX.search(s) or dom.endswith(".gov.tw"):
        return "tax"
    if _domain_in(dom, company_domains):
        return "company"
    if _CARD.search(s):
        return "card"
    if _BILL.search(s):
        return "bill"
    if _RECEIPT.search(s):
        return "receipt"
    if _TRAVEL.search(s):
        return "travel"
    if h.unsub or _PROMO.search(s):
        return "promo"
    return None
