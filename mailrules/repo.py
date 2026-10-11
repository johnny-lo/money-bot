"""空殼：Task 2 實作。"""
from .types import Rule


def card_rules(db, card: str) -> list[Rule]: raise NotImplementedError
def confirm_card(db, card: str, rejected_ids: list[int]) -> tuple[int, int]: raise NotImplementedError
def assign(db, rule_id: int, category: str) -> None: raise NotImplementedError
def rejected_rules(db) -> list[Rule]: raise NotImplementedError
def pending_cards(db) -> list[str]: raise NotImplementedError
def reject(db, card: str, ids: list[int]) -> int: raise NotImplementedError
