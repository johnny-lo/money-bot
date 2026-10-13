"""bridge.post_sync_wait 的迴圈守衛：在 bot 自己的 event loop 裡呼叫會等自己（卡死到逾時），所以要直接回 False、不送出。"""
import asyncio
import time

from discordbot import bridge
from tests.test_bridge_post_wait import Chan, _bot


def test_在_bot_自己的_loop_裡呼叫_回_False_不送出(monkeypatch, capsys):
    ch, made = Chan(), []

    async def go():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, ch))
        t0 = time.monotonic()
        ok = bridge.post_sync_wait(5, ["E"], make_view=lambda: made.append(1) or "VIEW", timeout=3)
        took = time.monotonic() - t0
        await asyncio.sleep(0.05)                 # 萬一排進了 loop，給它機會跑：仍不能送出
        return ok, took

    ok, took = asyncio.run(go())
    assert ok is False
    assert took < 1                               # 守衛直接回，不是等到逾時才回 False
    assert ch.sent == [] and made == []
    assert "不能在 bot 的 event loop 裡呼叫" in capsys.readouterr().out
