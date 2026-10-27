"""中信 LINE 通知的 Discord 端：codex 也看不懂的通知、listener 被登出／停擺告警。

發到刷卡比對同一個頻道（DISCORD_INVOICE_CHANNEL_ID）。通知文字是外來的，進 embed 前先跳脫 markdown 與 mention。
"""
import os

import discord

from lineinbox.config import STALE_MIN
from lineinbox.types import InboxMessage, ListenerState

from .bridge import post_sync

COLOR = 0xE74C3C
_MAX_TEXTS = 12
_MAX_CHARS = 1000
_DESC_LIMIT = 4096
RELOGIN = (
    "重新登入：在 `~/Desktop/linebot` 跑\n"
    "`docker compose run --rm line okline login --save /data/tokens.json --wait 240`\n"
    "手機掃 QR、確認 PIN；listener 會自己發現新的登入接著收，不用重啟。"
)


def _chan() -> int | None:
    v = os.getenv("DISCORD_INVOICE_CHANNEL_ID", "").strip()
    return int(v) if v.isdigit() else None


def _safe(text: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text))


def _segment(item: InboxMessage) -> str:
    # 跳脫後才截：先截再跳脫會超過上限；尾端落單的反斜線會吃掉下一段的換行，去掉
    head = f"**{item.sent_at:%m/%d %H:%M}**\n"
    body = _safe("\n".join(item.texts[:_MAX_TEXTS]))[:_MAX_CHARS - len(head)].rstrip("\\")
    return head + body


def notify_unreadable(items: list[InboxMessage]) -> None:
    """每則一段（時間＋前 12 段文字）；超過 embed 上限就分成多則訊息。"""
    ch = _chan()
    if not ch or not items:
        return
    title = f"🧾 有 {len(items)} 則中信 LINE 通知看不懂，請手動確認"
    pages, cur = [], ""
    for seg in map(_segment, items):
        if cur and len(cur) + 2 + len(seg) > _DESC_LIMIT:
            pages.append(cur)
            cur = ""
        cur = f"{cur}\n\n{seg}" if cur else seg
    pages.append(cur)
    for desc in pages:
        e = discord.Embed(title=title, description=desc, color=COLOR)
        e.set_footer(text="中信 LINE 通知 · 程式與 codex 都拆不出刷卡")
        post_sync(ch, [e])


def _span(minutes: int) -> str:
    return f"{minutes // 60} 小時" if minutes % 60 == 0 else f"{minutes} 分鐘"


def notify_listener(kind: str, state: ListenerState) -> None:
    ch = _chan()
    if not ch:
        return
    head = "LINE 被登出了，收不到中信刷卡通知。" if kind == "kicked" else f"LINE listener 超過 {_span(STALE_MIN)}沒有心跳。"
    lines = [head]
    if state is not None and state.last_error:
        lines.append(f"最後錯誤：{_safe(state.last_error)}")
    if state is not None and state.heartbeat_at:
        lines.append(f"最後心跳：{state.heartbeat_at:%m/%d %H:%M}")
    lines += ["", RELOGIN]
    e = discord.Embed(title="⚠️ 中信 LINE 通知 listener", description="\n".join(lines), color=COLOR)
    post_sync(ch, [e])
