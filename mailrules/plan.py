"""空殼：Task 1 實作。"""
from datetime import date
from .types import Action, MailHeader, MessageState, Verdict


def school_label(from_addr: str) -> str: raise NotImplementedError
def plan_actions(h: MailHeader, v: Verdict, st: MessageState, today: date, mode: str) -> list[Action]: raise NotImplementedError
