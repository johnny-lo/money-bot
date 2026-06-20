"""Discord bot package（原單檔 discord_handler.py 拆分而來，邏輯不變）。

模組分工：
- bot.py             MoneyBot client（事件路由）+ create_discord_bot
- commands.py        28 個 slash commands 註冊
- embeds.py          所有 embed builders（純呈現）
- ingest_handlers.py 美食/食譜/圖片記帳的 on_message 處理
- reports.py         週報/月報/發票通知（DB 彙總 + 推播）
- bridge.py          sync→async 橋接（排程 thread 投遞 embeds）

注意：package 不能命名為 `discord`，會遮蔽 discord.py 套件。
"""
from .bot import MoneyBot, create_discord_bot
from .bridge import set_bot, post_embeds_sync
from .reports import (
    notify_invoice_sync,
    notify_invoice_failure,
    notify_weekly_summary,
    notify_monthly_summary,
)

__all__ = [
    "MoneyBot", "create_discord_bot",
    "set_bot", "post_embeds_sync",
    "notify_invoice_sync", "notify_invoice_failure",
    "notify_weekly_summary", "notify_monthly_summary",
]
