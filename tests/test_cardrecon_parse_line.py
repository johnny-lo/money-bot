import json
from datetime import date
from pathlib import Path

from cardrecon.parse import foreign_amount, parse_ctbc_line
from cardrecon.types import Charge
from lineinbox.flex import message_parts


FIXTURES = Path(__file__).parent / "fixtures" / "ctbc_line"


def _texts(name: str) -> list[str]:
    msg = json.loads((FIXTURES / f"{name}.json").read_text())
    return message_parts(msg)[2]


def test_store_charge():
    charge = parse_ctbc_line(_texts("store"))

    assert charge == Charge(
        source="ctbc_line",
        card_last4="1234",
        charge_date=date(2026, 9, 5),
        charge_time="19:42",
        amount=1280,
        merchant="XX炸雞-測試店",
        line_no=0,
        region=None,
        merchant_type=None,
    )


def test_online_charge_has_transaction_and_merchant_types():
    charge = parse_ctbc_line(_texts("online"))

    assert charge is not None
    assert (charge.amount, charge.merchant, charge.pay_method, charge.merchant_type) == (
        359,
        None,
        "非實體卡交易",
        "居家/修繕/3C家電",
    )


def test_foreign_amount_is_rejected_regardless_of_currency_code():
    for name in ("foreign_usd", "foreign_twd"):
        flattened = _texts(name)
        assert foreign_amount(flattened) is True
        assert parse_ctbc_line(flattened) is None


def test_missing_amount_or_invalid_time_returns_none():
    flattened = _texts("store")

    assert parse_ctbc_line([part for part in flattened if part != "NT$1,280"]) is None
    assert parse_ctbc_line([
        "2026/9/5" if part == "2026/09/05  19:42" else part
        for part in flattened
    ]) is None


def test_single_digit_hour_is_zero_padded():
    flattened = [
        "2026/9/5  7:05" if part == "2026/09/05  19:42" else part
        for part in _texts("store")
    ]

    charge = parse_ctbc_line(flattened)

    assert charge is not None
    assert (charge.charge_date, charge.charge_time) == (date(2026, 9, 5), "07:05")


def test_card_last_four_must_be_exactly_four_digits():
    flattened = ["12X4" if part == "1234" else part for part in _texts("store")]

    assert parse_ctbc_line(flattened) is None
