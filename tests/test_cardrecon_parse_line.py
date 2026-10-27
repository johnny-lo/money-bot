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


def test_實體店刷卡():
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


def test_網路消費帶交易類型與商店類型():
    charge = parse_ctbc_line(_texts("online"))

    assert charge is not None
    assert (charge.amount, charge.merchant, charge.pay_method, charge.merchant_type) == (
        359,
        None,
        "非實體卡交易",
        "居家/修繕/3C家電",
    )


def test_外幣金額不論幣別都拒絕():
    for name in ("foreign_usd", "foreign_twd"):
        flattened = _texts(name)
        assert foreign_amount(flattened) is True
        assert parse_ctbc_line(flattened) is None


def test_缺少金額或時間格式錯誤時回None():
    flattened = _texts("store")

    assert parse_ctbc_line([part for part in flattened if part != "NT$1,280"]) is None
    assert parse_ctbc_line([
        "2026/9/5" if part == "2026/09/05  19:42" else part
        for part in flattened
    ]) is None


def test_單位數小時補零():
    flattened = [
        "2026/9/5  7:05" if part == "2026/09/05  19:42" else part
        for part in _texts("store")
    ]

    charge = parse_ctbc_line(flattened)

    assert charge is not None
    assert (charge.charge_date, charge.charge_time) == (date(2026, 9, 5), "07:05")


def test_卡末四碼必須是四位數字():
    flattened = ["12X4" if part == "1234" else part for part in _texts("store")]

    assert parse_ctbc_line(flattened) is None


def test_商店名稱只有空白時為None():
    flattened = ["  " if part == "ＸＸ炸雞－測試店" else part for part in _texts("store")]

    charge = parse_ctbc_line(flattened)

    assert charge is not None
    assert charge.merchant is None
