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


def post_sync_wait(channel_id: int, embeds: list[discord.Embed], make_view=None, timeout: float = 30) -> bool:
    """同 post_sync，但等 Discord 的送出結果：真的送出才回 True；頻道沒設、bot 沒 ready、送失敗、逾時都回 False。
    呼叫端靠它決定「記不記成已發」。會卡住呼叫的 thread → 只能在排程 thread 或 asyncio.to_thread 裡用，
    不能在 bot 自己的 event loop 裡呼叫（會等自己）。"""
    bot = _bot_instance
    if not bot or not channel_id:
        return False
    try:
        loop = bot.loop
        ready = loop is not None and not loop.is_closed() and bot.is_ready()
    except Exception:                     # discord.py 還沒 setup 時讀 bot.loop 會丟 AttributeError
        ready = False
    if not ready:
        print("⚠️ Discord bot 還沒 ready，沒發出去")
        return False
    try:
        if asyncio.get_running_loop() is loop:
            print("⚠️ post_sync_wait 不能在 bot 的 event loop 裡呼叫，沒發出去")
            return False
    except RuntimeError:
        pass                              # 沒有 running loop＝一般 thread，正常

    async def _send():
        ch = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        kw = {"embeds": embeds}
        view = make_view() if make_view else None
        if view is not None:
            kw["view"] = view
        await ch.send(**kw)
        return True

    fut = asyncio.run_coroutine_threadsafe(_send(), loop)
    try:
        return fut.result(timeout) is True
    except Exception as e:                # 送失敗、逾時（逾時就取消；萬一其實送出了，下次會再發一次——寧可重複不可漏）
        fut.cancel()
        print(f"⚠️ Discord 通知失敗 (channel {channel_id})：{type(e).__name__}: {e}")
        return False
