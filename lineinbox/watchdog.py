"""money-bot 排程呼叫：拆不出來的中信 LINE 通知交給 codex、listener 停擺告警。

codex 只在 money-bot 容器裡有（money-line 不掛 ~/.codex），所以備援解析放在這裡，不放 listener。
"""
from datetime import datetime

import codex_cli
from cardrecon import repo as card_repo
from database import SessionLocal
from discordbot import lineinbox_ui

from . import health
from . import repo as line_repo
from .config import CHARGE_ID_PREFIX, CODEX_FALLBACK_MODEL, FALLBACK_PER_RUN, STALE_MIN
from .fallback import SCHEMA, build_prompt, charge_from_reply
from .types import CODEX_PARSED, UNREADABLE


def run(now: datetime | None = None, db=None) -> dict:
    own = db is None
    db = db or SessionLocal()
    try:
        return _run(db, now or datetime.now())   # 跟 repo.set_state 寫心跳用同一種 naive 時間
    finally:
        if own:
            db.close()


def _run(db, now: datetime) -> dict:
    parsed, unreadable = 0, []
    for item in line_repo.pending_codex(db, FALLBACK_PER_RUN):
        try:
            reply = codex_cli.codex_text(build_prompt(item.texts), model=CODEX_FALLBACK_MODEL, schema=SCHEMA)
        except Exception as e:
            reply, error = None, f"codex 失敗：{type(e).__name__}"
        else:
            error = "codex 回覆沒通過驗證"
        charge = charge_from_reply(reply, item.sent_at) if reply is not None else None
        if charge is None:
            line_repo.set_status(db, item.message_id, UNREADABLE, error)
            unreadable.append(item)
            continue
        card_repo.upsert_charges(db, CHARGE_ID_PREFIX + item.message_id, [charge])
        line_repo.set_status(db, item.message_id, CODEX_PARSED)
        parsed += 1
    if unreadable:
        lineinbox_ui.notify_unreadable(unreadable)

    state = line_repo.listener_state(db)
    kind = health.alert_kind(state, now, STALE_MIN)
    if health.should_send(kind, state.alerted if state else None):
        lineinbox_ui.notify_listener(kind, state)
        line_repo.mark_alerted(db, kind)
    return {"codex": parsed, "unreadable": len(unreadable), "alert": kind}
