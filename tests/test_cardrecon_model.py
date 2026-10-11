from datetime import date

from models import CardCharge
from cardrecon.types import Charge
from cardrecon import config


def test_card_charges_欄位():
    cols = set(CardCharge.__table__.columns.keys())
    assert cols == {"id", "message_id", "line_no", "source", "card_last4", "charge_date", "charge_time",
                    "post_date", "amount", "region", "merchant", "pay_method", "status", "matched_key",
                    "batch", "created_at", "updated_at"}


def test_同一封信同一行_唯一():
    uqs = [c for c in CardCharge.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({col.name for col in u.columns} == {"message_id", "line_no"} for u in uqs)


def test_charge_欄位都能直接塞進_model():
    c = Charge(source="sinopac_daily", card_last4="1234", charge_date=date(2026, 1, 2), amount=5, line_no=0)
    model_cols = set(CardCharge.__table__.columns.keys())
    assert set(c.__dataclass_fields__) <= model_cols


def test_config():
    assert config.LIST_FROM == date(2026, 4, 21)
    assert config.PAGE_SIZE == 25 and config.LIST_LAG_DAYS == 3 and config.LOOKBACK_DAYS == 60
    assert "mma@sinopac.com" not in {s for s, _ in config.CARD_SOURCES.values()}
