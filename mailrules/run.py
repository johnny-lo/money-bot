"""空殼：Task 2 實作。"""
from datetime import date
from .types import RunReport


def run_daily(today: date, db=None) -> RunReport: raise NotImplementedError
def prepare_history(today: date, db=None) -> int: raise NotImplementedError
def history_plan(today: date, db=None) -> dict: raise NotImplementedError
def execute_history(today: date, db=None) -> RunReport: raise NotImplementedError
