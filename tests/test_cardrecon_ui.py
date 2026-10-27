import asyncio
from datetime import date

import pytest

from cardrecon.types import Charge, WeeklyResult
from discordbot import cardrecon_ui as ui

D = date(2026, 10, 3)


def ch(amount, merchant=None, src="sinopac_daily", card="1234", region="US", time=None):
    return Charge(source=src, card_last4=card, charge_date=D, amount=amount, line_no=0, region=region,
                  merchant=merchant, charge_time=time)


@pytest.mark.parametrize("uid,owner,expect", [(1, 1, None), (2, 1, "只有"), (1, None, "AUTOFIX_OWNER_USER_ID")])
def test_can_act(uid, owner, expect):
    got = ui.can_act(uid, owner)
    assert (got is None) if expect is None else (expect in got)


def test_每行格式與狀態標記():
    assert ui.line(ch(2345)) == "10/03 永豐 US $2,345"
    assert ui.line(ch(690, "ACME *STREAMING", "ctbc_statement", "5678")) == "10/03 中信 US $690 ACME *STREAMING"
    assert ui.line(ch(5), "ignored").startswith("~~") and "已忽略" in ui.line(ch(5), "ignored")
    assert ui.line(ch(1500, time="23:12")) == "10/03 23:12 永豐 US $1,500"
    assert ui.line(ch(1500, time="23:12"), hint="同卡同金額 3 個月都有") == \
        "10/03 23:12 永豐 US $1,500 · 同卡同金額 3 個月都有"
    assert ui.line(ch(2345), hint="h") == "10/03 永豐 US $2,345 · h"
    assert "已有帳" in ui.line(ch(5), "matched") and "已補記" in ui.line(ch(5), "recorded")
    assert "1234" not in ui.line(ch(2345)) and "5678" not in ui.line(ch(690, src="ctbc_statement", card="5678"))


def test_page_embed_標題只算未處理的():
    items = [(1, ch(100), "unmatched", None), (2, ch(200), "ignored", None), (3, ch(300), "unmatched", None)]
    e = ui.page_embed("2026-10-18-1", items, page="1/2")
    assert "1/2" in e.title and "2 筆" in e.title and "$400" in e.title
    assert e.description.count("\n") == 2
    assert e.title.startswith("💳 疑似漏記")


def test_page_embed_有組別用中文標籤標題():
    e = ui.page_embed("b-1", [(1, ch(100), "unmatched", "h")], page="2/3", group="subscription")
    assert e.title == "💳 疑似訂閱或固定扣款 第 2/3 頁：1 筆，共 $100"
    assert "· h" in e.description


def test_custom_id_重啟後解析得回batch():
    m = ui.RecordButton.__discord_ui_compiled_template__.fullmatch("cardrecon:record:2026-10-18-3")
    assert m["batch"] == "2026-10-18-3"
    m = ui.IgnoreAllButton.__discord_ui_compiled_template__.fullmatch("cardrecon:ignoreall:2026-10-18-3")
    assert m["batch"] == "2026-10-18-3"
    m = ui.IgnoreSelect.__discord_ui_compiled_template__.fullmatch("cardrecon:ignore:2026-10-18-3")
    assert m["batch"] == "2026-10-18-3"


def test_page_view_只放未處理的選項_全處理完就沒有元件():
    async def go():
        items = [(1, ch(100), "unmatched", None), (2, ch(200), "ignored", None)]
        v = ui.page_view("b-1", items)
        ids = sorted(c.custom_id for c in v.children)
        assert ids == ["cardrecon:ignore:b-1", "cardrecon:ignoreall:b-1", "cardrecon:record:b-1"]
        sel = next(c for c in v.children if c.custom_id.startswith("cardrecon:ignore"))
        assert [o.value for o in sel.item.options] == ["1"]
        assert [o.label for o in sel.item.options] == ["10/03 永豐 US $100"]     # 選項也不標卡號
        assert ui.page_view("b-1", [(2, ch(200), "ignored", None)]) is None
    asyncio.run(go())


def test_notify_weekly_每頁一則_零筆不發(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda cid, embeds, make_view=None: sent.append((cid, embeds, make_view)))
    ui.notify_weekly(WeeklyResult())
    assert sent == []
    r = WeeklyResult(pages=[("x-1", "other", [(1, ch(100), None)]), ("x-2", "other", [(2, ch(200), None)])], total=300)
    ui.notify_weekly(r)
    assert [s[0] for s in sent] == [42, 42] and "1/2" in sent[0][1][0].title
    assert all(callable(s[2]) for s in sent)


def test_notify_weekly_頁碼按組別各自編(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda cid, embeds, make_view=None: sent.append(embeds[0].title))
    r = WeeklyResult(pages=[("x-1", "subscription", [(1, ch(100), "h")]), ("x-2", "small", [(2, ch(50), None)]),
                            ("x-3", "small", [(3, ch(60), None)])])
    ui.notify_weekly(r)
    assert "疑似訂閱" in sent[0] and "1/1" in sent[0]
    assert "小額" in sent[1] and "1/2" in sent[1] and "2/2" in sent[2]


def test_notify_weekly_零筆但有失敗信件_發警告(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda cid, embeds, make_view=None: sent.append(embeds))
    ui.notify_weekly(WeeklyResult(failed_mails=2))
    assert len(sent) == 1 and "2" in sent[0][0].description


def test_page_embed_description不超過4096():
    items = [(i, ch(100 + i), "unmatched", "同卡同金額 12 個月都有") for i in range(25)]
    e = ui.page_embed("b-1", items)
    assert len(e.description) <= 4096
    assert "同卡同金額 12 個月都有" in e.description


def test_line_網路消費顯示商店類型():
    c = Charge(source="ctbc_line", card_last4="1234", charge_date=D, amount=359, line_no=0, charge_time="10:05",
               merchant_type="居家/修繕/3C家電")
    assert ui.line(c) == "10/03 10:05 中信 $359 （居家/修繕/3C家電）"
    named = Charge(source="ctbc_line", card_last4="1234", charge_date=D, amount=1280, line_no=0, charge_time="19:42",
                   merchant="XX炸雞-測試店", merchant_type="餐飲")
    assert ui.line(named) == "10/03 19:42 中信 $1,280 XX炸雞-測試店"
    assert "1234" not in ui.line(c)


def test_line_summary():
    assert ui.line_summary(WeeklyResult(line_charges=3, merged=1)) is None
    assert ui.line_summary(WeeklyResult(line_charges=12, merged=4, line_state="ok")) == \
        "📡 LINE 中信通知：本週 12 筆 · 合併帳單 4 筆 · 狀態 正常"
    assert ui.line_summary(WeeklyResult(line_state="kicked")) == \
        "📡 LINE 中信通知：本週 0 筆 · 合併帳單 0 筆 · 狀態 被登出，要重新掃碼"
    assert ui.line_summary(WeeklyResult(line_state="error")).endswith("狀態 錯誤")
    assert ui.line_summary(WeeklyResult(line_state="starting")).endswith("狀態 啟動中")
    assert ui.line_summary(WeeklyResult(line_state="weird")).endswith("狀態 weird")


def test_notify_weekly_沒有清單頁也發LINE摘要(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda cid, embeds, make_view=None: sent.append((cid, embeds, make_view)))
    r = WeeklyResult(line_charges=5, merged=2, line_state="ok")
    ui.notify_weekly(r)
    assert len(sent) == 1 and sent[0][0] == 42 and len(sent[0][1]) == 1
    assert sent[0][1][0].description == ui.line_summary(r) and sent[0][2] is None


def test_notify_weekly_有清單頁也另發LINE摘要(monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_INVOICE_CHANNEL_ID", "42")
    monkeypatch.setattr(ui, "post_sync", lambda cid, embeds, make_view=None: sent.append(embeds))
    r = WeeklyResult(pages=[("x-1", "other", [(1, ch(100), None)])], line_charges=1, line_state="kicked")
    ui.notify_weekly(r)
    assert len(sent) == 2
    assert [e.description for e in sent[1]] == [ui.line_summary(r)]
    assert ui.line_summary(r) not in (sent[0][0].description or "")
