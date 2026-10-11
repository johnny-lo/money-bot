"""空殼：Task 2 實作。"""
from .types import Action, MailHeader


def imap_utf7_encode(s: str) -> str: raise NotImplementedError
def imap_utf7_decode(s: str) -> str: raise NotImplementedError
def read_headers(since_uid: int | None) -> tuple[int, list[MailHeader]]: raise NotImplementedError
def apply(actions: list[Action]) -> tuple[list[Action], list[Action]]: raise NotImplementedError
