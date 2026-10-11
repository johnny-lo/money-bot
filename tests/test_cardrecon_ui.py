import asyncio
from datetime import date

import pytest

from cardrecon.types import Charge, WeeklyResult
from discordbot import cardrecon_ui as ui

D = date(2026, 10, 3)


def ch(amount, merchant=None, src="sinopac_daily", card="1234", region="US"):
    return Charge(source=src, card_last4=card, charge_date=D, amount=amount, line_no=0, region=region, merchant=merchant)


@pytest.mark.parametrize("uid,owner,expect", [(1, 1, None), (2, 1, "只有"), (1, None, "AUTOFIX_OWNER_USER_ID")])
def test_can_act(uid, owner, expect):
    got = ui.can_act(uid, owner)
    assert (got is None) if expect is None else (expect in got)


def test_每行格式與狀態標記():
    assert ui.line(ch(2345)) == "10/03 永豐1234 US $2,345"
    assert ui.line(ch(690, "ACME *STREAMING", "ctbc_statement", "5678")) == "10/03 中信5678 US $690 ACME *STREAMING"
    assert ui.line(ch(5), "ignored").startswith("~~") and "已忽略" in ui.line(ch(5), "ignored")
    assert "已有帳" in ui.line(ch(5), "matched") and "已補記" in ui.line(ch(5), "recorded")


def test_page_embed_標題只算未處理的():
    items = [(1, ch(100), "unmatched"), (2, ch(200), "ignored"), (3, ch(300), "unmatched")]
    e = ui.page_embed("2026-10-18-1", items, page="1/2")
    assert "1/2" in e.title and "2 筆" in e.title and "$400" in e.title
    assert e.description.count("\n") == 2


def test_custom_id_重啟後解析得回batch():
    m = ui.RecordButton.__discord_ui_compiled_template__.fullmatch("cardrecon:record:2026-10-18-3")
    assert m["batch"] == "2026-10-18-3"
    m = ui.IgnoreSelect.__discord_ui_compiled_template__.fullmatch("cardrecon:ignore:2026-10-18-3")
    assert m["batch"] == "2026-10-18-3"


def test_page_view_只放未處理的選項_全處理完就沒有元件():
    async def go():
        items = [(1, ch(100), "unmatched"), (2, ch(200), "ignored")]
        v = ui.page_view("b-1", items)
        ids = sorted(c.custom_id for c in v.children)
        assert ids == ["cardrecon:ignore:b-1", "cardrecon:record:b-1"]
        sel = next(c for c in v.children if c.custom_id.startswith("cardrecon:ignore"))
        assert [o.value for o in sel.item.options] == ["1"]
        assert ui.page_view("b-1", [(2, ch(200), "ignored")]) is None
    asyncio.run(go())


def test_notify_weekly_每頁一則_零筆不發(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda cid, embeds, make_view=None: sent.append((cid, embeds, make_view)))
    ui.notify_weekly(WeeklyResult())
    assert sent == []
    r = WeeklyResult(pages=[("x-1", [(1, ch(100))]), ("x-2", [(2, ch(200))])], total=300)
    ui.notify_weekly(r)
    assert [s[0] for s in sent] == [42, 42] and "1/2" in sent[0][1][0].title
    assert all(callable(s[2]) for s in sent)


def test_notify_weekly_零筆但有失敗信件_發警告(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda cid, embeds, make_view=None: sent.append(embeds))
    ui.notify_weekly(WeeklyResult(failed_mails=2))
    assert len(sent) == 1 and "2" in sent[0][0].description
