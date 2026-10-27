import re
from datetime import datetime

from discordbot import lineinbox_ui as ui
from lineinbox.types import InboxMessage, ListenerState


NOW = datetime(2026, 10, 27, 12, 0)


def test_看不懂的通知會跳脫外來文字再送出(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda channel_id, embeds: sent.append((channel_id, embeds)))
    item = InboxMessage(
        message_id="900000000000000001",
        source="ctbc",
        sent_at=NOW,
        alt_text=None,
        content_type=22,
        texts=["[x](http://evil)", "@everyone"] + [f"合成段落{i}" for i in range(3, 15)],
        kind="spend",
    )

    ui.notify_unreadable([item])

    assert len(sent) == 1 and sent[0][0] == 42
    description = sent[0][1][0].description
    # 遮罩連結的 [ 前面要有反斜線，Discord 才會照字面顯示、不變成連結
    assert re.search(r"(?<!\\)\[x\]\(http://evil\)", description) is None
    assert "\\[x](http://evil)" in description
    assert "@everyone" not in description
    assert "@\u200beveryone" in description
    assert "http://evil" in description
    assert "合成段落12" in description
    assert "合成段落13" not in description
    assert len(description) <= 1000


def test_沒有頻道就不發通知(monkeypatch):
    sent = []
    monkeypatch.delenv("DISCORD_INVOICE_CHANNEL_ID", raising=False)
    monkeypatch.setattr(ui, "post_sync", lambda *args, **kwargs: sent.append(args))

    ui.notify_unreadable([])
    ui.notify_listener("kicked", ListenerState("kicked", NOW, None, None))

    assert sent == []


def test_listener告警附重新登入指令與停擺錯誤(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda channel_id, embeds: sent.append((channel_id, embeds[0])))
    command = "docker compose run --rm line okline login --save /data/tokens.json --wait 240"

    ui.notify_listener("kicked", ListenerState("kicked", NOW, None, None))
    ui.notify_listener("stale", ListenerState("ok", NOW, "合成連線錯誤", None))

    assert len(sent) == 2
    assert "LINE 被登出了" in sent[0][1].description
    assert command in sent[0][1].description
    assert "超過 1 小時沒有心跳" in sent[1][1].description
    assert "合成連線錯誤" in sent[1][1].description
    assert command in sent[1][1].description
