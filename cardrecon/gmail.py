"""空殼：Task 3 實作。"""
from datetime import date
from .types import RawMail


def fetch(sender: str, subject_kw: str, since: date | None = None) -> list[RawMail]: raise NotImplementedError
