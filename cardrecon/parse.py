"""空殼：Task 1 實作。"""
from .types import Charge, Receipt


def decode_glyph_names(text: str) -> str: raise NotImplementedError
def parse_sinopac(text: str) -> list[Charge]: raise NotImplementedError
def parse_ctbc(text: str) -> list[Charge]: raise NotImplementedError
def parse_autopass(text: str) -> Receipt | None: raise NotImplementedError


PARSERS = {"sinopac_daily": parse_sinopac, "ctbc_statement": parse_ctbc}
