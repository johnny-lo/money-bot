"""空殼：Task 3 實作。"""
from .types import Charge, RecordResult


def batch_items(db, batch: str) -> list[tuple[int, Charge, str]]: raise NotImplementedError
def ignore(db, batch: str, ids: list[int]) -> int: raise NotImplementedError
def record(db, batch: str) -> RecordResult: raise NotImplementedError
