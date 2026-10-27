"""一則被監看帳號的 LINE 訊息 → 分類 → 寫進 card_charges／line_messages。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from cardrecon import repo as card_repo
from cardrecon.parse import foreign_amount, parse_ctbc_line
from cardrecon.types import Charge

from . import flex
from . import repo as inbox_repo
from .config import CHARGE_ID_PREFIX
from .types import NEEDS_CODEX, NON_TWD, OTHER, PARSED, InboxMessage

PARSERS = {"ctbc": parse_ctbc_line}   # config.WATCHED 的來源鍵 → 消費通知 parser

_TZ = ZoneInfo("Asia/Taipei")


def _sent_at(created_ms) -> datetime:
    """LINE createdTime（epoch 毫秒）→ 台北時間 naive，跟 DB 其他時間欄位一致。"""
    return datetime.fromtimestamp(int(created_ms) / 1000, _TZ).replace(tzinfo=None)


def classify(msg: dict, source: str) -> tuple[InboxMessage, str, Charge | None]:
    """純函式：不碰 DB。有外幣金額時通知上的台幣只是約當金額，不建刷卡。"""
    alt, content_type, texts = flex.message_parts(msg)
    spend = flex.is_spend(alt, texts)
    m = InboxMessage(message_id=str(msg["id"]), source=source, sent_at=_sent_at(msg["createdTime"]),
                     alt_text=alt, content_type=content_type, texts=texts,
                     kind="spend" if spend else "other")
    if not spend:
        return m, OTHER, None
    if foreign_amount(texts):
        return m, NON_TWD, None
    charge = PARSERS[source](texts)
    if charge is None:
        return m, NEEDS_CODEX, None
    return m, PARSED, charge


def handle(db, msg: dict, source: str) -> str | None:
    """已處理過的回 None、什麼都不寫（補讀會重複看到同一則）。
    刷卡先寫、訊息後存：刷卡寫入失敗時訊息不存，下次補讀會整則重做。"""
    if inbox_repo.exists(db, str(msg["id"])):
        return None
    m, status, charge = classify(msg, source)
    if status == PARSED:
        card_repo.upsert_charges(db, CHARGE_ID_PREFIX + m.message_id, [charge])
    inbox_repo.save_message(db, m, status)
    return status
