"""Sync→Async bridge：給排程（APScheduler 同步 thread）把 embeds 投遞到 Discord 用。

原理：把 coroutine 用 asyncio.run_coroutine_threadsafe(coro, bot.loop) 排到 bot 的 event loop。
注意 _bot_instance 是 module 級狀態——notify_*() 必須在 bot 主進程內呼叫，
從 docker compose exec 開的子進程呼叫會靜默失敗（bot 還沒 set_bot）。
"""
import asyncio

import discord

_bot_instance: discord.Client | None = None


def set_bot(bot: discord.Client) -> None:
    global _bot_instance
    _bot_instance = bot


def post_embeds_sync(channel_id: int, embeds: list[discord.Embed]) -> None:
    """Threadsafe：從非 async thread 投遞 embeds 到指定 channel。"""
    bot = _bot_instance
    if not bot or not channel_id:
        return
    loop = bot.loop
    if not loop or loop.is_closed():
        print("⚠️ Discord bot 還沒 ready，跳過通知")
        return

    async def _send():
        try:
            ch = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            await ch.send(embeds=embeds)
        except Exception as e:
            print(f"⚠️ Discord 通知失敗 (channel {channel_id})：{e}")

    asyncio.run_coroutine_threadsafe(_send(), loop)


def post_sync(channel_id: int, embeds: list[discord.Embed], make_view=None) -> None:
    """同 post_embeds_sync，但可附元件。make_view 在 bot loop 內才呼叫（View 不能在排程 thread 建）。"""
    bot = _bot_instance
    if not bot or not channel_id:
        return
    loop = bot.loop
    if not loop or loop.is_closed():
        print("⚠️ Discord bot 還沒 ready，跳過通知")
        return

    async def _send():
        try:
            ch = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            kw = {"embeds": embeds}
            view = make_view() if make_view else None
            if view is not None:
                kw["view"] = view
            await ch.send(**kw)
        except Exception as e:
            print(f"⚠️ Discord 通知失敗 (channel {channel_id})：{e}")

    asyncio.run_coroutine_threadsafe(_send(), loop)
