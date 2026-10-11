"""空殼：Task 1 實作。"""
from .types import MailHeader, Rule, Verdict


def has_job_keyword(subject: str) -> bool: raise NotImplementedError
def is_human(h: MailHeader) -> bool: raise NotImplementedError
def learn_valued_domains(headers: list[MailHeader], self_addrs: set[str], company_domains: set[str]) -> dict[str, str]: raise NotImplementedError
def match_rule(h: MailHeader, pattern: str, rules: list[Rule]) -> Rule | None: raise NotImplementedError
def classify(h: MailHeader, pattern: str, rules: list[Rule], valued: set[str], self_addrs: set[str]) -> Verdict: raise NotImplementedError
def builtin_suggest(h: MailHeader, pattern: str, company_domains: set[str]) -> str | None: raise NotImplementedError
