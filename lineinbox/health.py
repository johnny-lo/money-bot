"""listener 健康判斷（純函式）：要不要告警、同一種告警發過就不再發。"""
from datetime import datetime, timedelta

from .types import KICKED, ListenerState


def alert_kind(state: ListenerState | None, now: datetime, stale_min: int) -> str | None:
    """被踢優先；心跳停住（錯誤或程序死掉時 heartbeat_at 不前進）超過 stale_min 分鐘視為停擺。"""
    if state is None:
        return None
    if state.state == KICKED:
        return "kicked"
    if state.heartbeat_at is None or now - state.heartbeat_at > timedelta(minutes=stale_min):
        return "stale"
    return None


def should_send(kind: str | None, alerted: str | None) -> bool:
    """alerted 在狀態恢復 OK 時由 repo.set_state 清掉，所以同一次故障只發一次。"""
    return kind is not None and kind != alerted
