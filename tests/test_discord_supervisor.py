"""run_discord_bot 監管迴圈：暫時性失敗自動重試、永久性失敗停手。

無 pytest-asyncio → 照 repo 慣例用 asyncio.run 驅動 coroutine。
用注入的 fake bot / fake sleep，完全不碰真網路、不真的 sleep。
"""
import asyncio

import discord

from discordbot.bot import run_discord_bot


class _FakeBot:
    """假 client：start() 呼叫注入的 behavior（可 return 或 raise）。"""

    def __init__(self, behavior):
        self._behavior = behavior
        self._closed = False

    async def start(self, token):
        return self._behavior()

    def is_closed(self):
        return self._closed

    async def close(self):
        self._closed = True


async def _noop_sleep(_seconds):
    return None


def test_transient_failure_retries_until_connected():
    """開機 DNS/連線暫時失敗 → 自動重試直到接上，不會永久死。"""
    attempts = {"n": 0}

    def make_bot():
        attempts["n"] += 1
        n = attempts["n"]

        def behavior():
            if n < 3:
                raise ConnectionError("Temporary failure in name resolution")
            return None  # 第 3 次乾淨連上（start 正常返回）

        return _FakeBot(behavior)

    asyncio.run(run_discord_bot("tok", create_bot=make_bot, sleep=_noop_sleep))

    assert attempts["n"] == 3  # 前兩次失敗重試，第 3 次成功後收工


def test_invalid_token_stops_without_retry():
    """token 無效（LoginFailure）→ 立刻停手，不無限重敲 Discord。"""
    attempts = {"n": 0}

    def make_bot():
        attempts["n"] += 1

        def behavior():
            raise discord.LoginFailure("Improper token has been passed.")

        return _FakeBot(behavior)

    async def _sleep_must_not_run(_seconds):
        raise AssertionError("永久性失敗不該進到退避 sleep")

    asyncio.run(run_discord_bot("bad", create_bot=make_bot, sleep=_sleep_must_not_run))

    assert attempts["n"] == 1  # 只嘗試一次就停
