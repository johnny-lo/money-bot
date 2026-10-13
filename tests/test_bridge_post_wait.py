"""bridge.post_sync_wait：排程 thread 等 Discord 真的送出才回 True（信件確認卡／計畫卡「已發」的依據）。"""
import asyncio
import threading
from types import SimpleNamespace

from discordbot import bridge


class LoopThread:
    """另開一條 thread 跑 event loop，模擬 bot 的 loop（呼叫端在排程 thread）。"""
    def __enter__(self):
        self.loop = asyncio.new_event_loop()
        self.t = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.t.start()
        return self.loop

    def __exit__(self, *a):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.t.join(5)
        self.loop.close()


class Chan:
    def __init__(self, boom=None, delay=0.0):
        self.sent, self.boom, self.delay = [], boom, delay

    async def send(self, **kw):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.boom:
            raise self.boom
        self.sent.append(kw)


def _bot(loop, ch, ready=True):
    async def fetch(cid):
        return ch
    return SimpleNamespace(loop=loop, is_ready=lambda: ready, get_channel=lambda cid: None, fetch_channel=fetch)


def test_送出成功才回_True_view_在_bot_loop_裡建(monkeypatch):
    ch, where = Chan(), []

    def mk():
        where.append(asyncio.get_running_loop() is loop)
        return "VIEW"
    with LoopThread() as loop:
        monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, ch))
        assert bridge.post_sync_wait(5, ["E"], make_view=mk) is True
    assert ch.sent == [{"embeds": ["E"], "view": "VIEW"}] and where == [True]


def test_沒有_view_也能發(monkeypatch):
    ch = Chan()
    with LoopThread() as loop:
        monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, ch))
        assert bridge.post_sync_wait(5, ["E"]) is True
    assert ch.sent == [{"embeds": ["E"]}]


def test_送失敗回_False(monkeypatch):
    with LoopThread() as loop:
        monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, Chan(boom=RuntimeError("403 Forbidden"))))
        assert bridge.post_sync_wait(5, ["E"]) is False


def test_逾時回_False(monkeypatch):
    ch = Chan(delay=2)
    with LoopThread() as loop:
        monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, ch))
        assert bridge.post_sync_wait(5, ["E"], timeout=0.05) is False
    assert ch.sent == []


def test_沒有_bot_沒頻道_沒_ready_都回_False(monkeypatch):
    monkeypatch.setattr(bridge, "_bot_instance", None)
    assert bridge.post_sync_wait(5, ["E"]) is False
    with LoopThread() as loop:
        ch = Chan()
        monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, ch))
        assert bridge.post_sync_wait(None, ["E"]) is False
        monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, ch, ready=False))
        assert bridge.post_sync_wait(5, ["E"]) is False
    assert ch.sent == []


def test_loop_已關_回_False(monkeypatch):
    loop = asyncio.new_event_loop()
    loop.close()
    monkeypatch.setattr(bridge, "_bot_instance", _bot(loop, Chan()))
    assert bridge.post_sync_wait(5, ["E"]) is False


def test_原本的_post_sync_仍是射後不理_不回結果(monkeypatch):
    monkeypatch.setattr(bridge, "_bot_instance", None)
    assert bridge.post_sync(5, ["E"]) is None and bridge.post_embeds_sync(5, ["E"]) is None
