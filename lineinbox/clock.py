"""lineinbox 共用的現在時間：台北時間 naive。

容器 TZ 沒設時 datetime.now() 是 UTC；line_messages.sent_at 存台北 naive，
心跳寫入（repo.set_state）與停擺判斷（watchdog.run）也必須用同一個基準，否則差 8 小時。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def now_taipei() -> datetime:
    return datetime.now(TAIPEI).replace(tzinfo=None)
