import json
from datetime import datetime

import pytest

from cardrecon.types import Charge
from lineinbox.fallback import SCHEMA, build_prompt, charge_from_reply


SENT_AT = datetime(2026, 9, 5, 20, 0)


def _reply(**changes) -> str:
    value = {
        "amount": 1280,
        "card_last4": "1234",
        "date": "2026-09-05",
        "time": "19:42",
        "merchant": "ＸＸ炸雞－測試店",
        "foreign": False,
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False)


def test_charge_from_reply_accepts_valid_json_and_normalizes_merchant():
    charge = charge_from_reply(_reply(), SENT_AT)

    assert charge == Charge(
        source="ctbc_line",
        card_last4="1234",
        charge_date=SENT_AT.date(),
        charge_time="19:42",
        amount=1280,
        merchant="XX炸雞-測試店",
        line_no=0,
    )


def test_charge_from_reply_rejects_foreign_charge():
    assert charge_from_reply(_reply(foreign=True), SENT_AT) is None


@pytest.mark.parametrize("changes", [
    {"amount": 0},
    {"amount": -1},
    {"card_last4": "123"},
    {"card_last4": "12X4"},
])
def test_charge_from_reply_rejects_invalid_amount_or_card(changes):
    assert charge_from_reply(_reply(**changes), SENT_AT) is None


def test_charge_from_reply_rejects_date_more_than_one_day_from_message():
    assert charge_from_reply(_reply(date="2026-09-03"), SENT_AT) is None
    assert charge_from_reply(_reply(date="2026-09-07"), SENT_AT) is None


@pytest.mark.parametrize("changes", [
    {"date": "2026/09/05"},
    {"date": "2026-02-30"},
    {"time": "7:05"},
    {"time": "24:00"},
])
def test_charge_from_reply_rejects_invalid_date_or_time_format(changes):
    assert charge_from_reply(_reply(**changes), SENT_AT) is None


def test_charge_from_reply_returns_none_for_invalid_json():
    assert charge_from_reply("{", SENT_AT) is None


def test_charge_from_reply_turns_empty_or_long_merchant_into_none():
    assert charge_from_reply(_reply(merchant="  "), SENT_AT).merchant is None
    assert charge_from_reply(_reply(merchant="x" * 61), SENT_AT).merchant is None


def test_build_prompt_marks_input_untrusted_and_includes_text():
    prompt = build_prompt(["刷卡通知", "NT$1,280"])

    assert "不可信" in prompt
    assert "刷卡通知" in prompt
    assert "NT$1,280" in prompt


def test_schema_requires_all_fields_and_rejects_additional_properties():
    assert set(SCHEMA["required"]) == {
        "amount", "card_last4", "date", "time", "merchant", "foreign",
    }
    assert SCHEMA["additionalProperties"] is False
