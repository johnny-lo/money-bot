"""lineinbox 各層之間的資料契約（無 I/O）。"""
from dataclasses import dataclass
from datetime import datetime

# line_messages.status
PARSED = "parsed"              # 程式拆出刷卡、已寫進 card_charges
NEEDS_CODEX = "needs_codex"    # 是消費通知但拆不出來，等 watchdog 交給 codex
CODEX_PARSED = "codex_parsed"  # codex 拆出來、已寫進 card_charges
UNREADABLE = "unreadable"      # codex 也不行，已發 Discord 給本人看
NON_TWD = "non_twd"            # 海外商店（有外幣金額）：通知的台幣只是約當金額，等帳單
OTHER = "other"                # 不是消費通知（入帳、廣告…）

# line_listener_state.state
STARTING = "starting"
OK = "ok"
KICKED = "kicked"              # session 被 LINE 踢掉，要本人重新掃碼
ERROR = "error"


@dataclass(frozen=True)
class InboxMessage:
    message_id: str                # LINE message id（不含前綴）
    source: str                    # config.WATCHED 的值
    sent_at: datetime              # 台北時間 naive
    alt_text: str | None
    content_type: int | None
    texts: list[str]               # 攤平後的文字段落
    kind: str                      # "spend" | "other"


@dataclass(frozen=True)
class ListenerState:
    state: str
    heartbeat_at: datetime | None
    last_error: str | None
    alerted: str | None
