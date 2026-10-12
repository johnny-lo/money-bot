import asyncio
import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from discordbot import mailrules_ui as ui
from mailrules.types import MailHeader, Rule, RunReport


def R(i, sender, cat="promo"):
    return Rule(id=i, sender=sender, subject_pattern="本週 # 折", category=cat, status="suggested",
                suggested_by="ai", card="s3")


def test_can_act():
    assert ui.can_act(1, 1) is None and "只有" in ui.can_act(2, 1) and ui.can_act(1, None)


def test_custom_id_重啟後解析得回():
    assert ui.ConfirmButton.__discord_ui_compiled_template__.fullmatch("mailrules:confirm:s12")["card"] == "s12"
    assert ui.RejectSelect.__discord_ui_compiled_template__.fullmatch("mailrules:reject:s12")["card"] == "s12"
    assert ui.AssignSelect.__discord_ui_compiled_template__.fullmatch("mailrules:assign:42")["rid"] == "42"


def test_建議卡標題與行():
    e = ui.suggest_embed("s3", [R(1, "news@shop.example"), R(2, "promo@x.example")],
                         {("news@shop.example", "本週 # 折"): 30})
    assert "推銷" in e.title and "2" in e.title
    assert "news@shop.example" in e.description and "30" in e.description and len(e.description) <= 4096


def test_摘要卡一行一封_截長():
    hs = [MailHeader(gm_msgid=str(i), uid=i, from_addr="jobs@board.example", from_name="", subject="工程師" * 40,
                     sent_date=None, labels=(), unsub=True, in_inbox=False) for i in range(200)]
    e = ui.digest_embed("💼 今日職缺", hs)
    assert len(e.description) <= 4096 and e.description.count("\n") >= 1


def test_每日報告未執行時說明():
    e = ui.daily_embed(RunReport(applied=False, unknown_patterns=5))
    assert "歷史整理完成前" in e.description and "5" in e.description


def test_建議卡_view_含拒絕下拉與確認鈕():
    async def go():
        v = ui.suggest_view("s3", [R(1, "a@x.example"), R(2, "b@x.example")])
        ids = sorted(c.custom_id for c in v.children)
        assert ids == ["mailrules:confirm:s3", "mailrules:reject:s3"]
    asyncio.run(go())


# ── 第二輪審查補的測試 ──────────────────────────────────────────

def _fake_interaction(values=None, uid=1):
    return SimpleNamespace(
        user=SimpleNamespace(id=uid, display_name="本人"),
        data={"values": values or []},
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        message=SimpleNamespace(edit=AsyncMock()),
    )


def test_執行鈕結果編輯原訊息_不用會過期的_followup(monkeypatch):
    from mailrules import run
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(run, "execute_history",
                        lambda today, db=None, upto_card=None: RunReport(applied=True, counts={("promo", "trash"): 7}))
    it = _fake_interaction()

    async def go():
        await ui.ExecuteButton("s3").callback(it)
    asyncio.run(go())
    it.response.edit_message.assert_awaited_once()
    assert "執行中" in it.response.edit_message.await_args.kwargs["embed"].title
    it.message.edit.assert_awaited_once()
    assert "完成" in it.message.edit.await_args.kwargs["embed"].title
    assert it.message.edit.await_args.kwargs["view"] is None
    it.followup.send.assert_not_awaited()


def test_執行鈕失敗也編輯原訊息(monkeypatch):
    from mailrules import run

    def boom(today, db=None, upto_card=None):
        raise RuntimeError("IMAP 斷線")
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(run, "execute_history", boom)
    it = _fake_interaction()

    async def go():
        await ui.ExecuteButton("s3").callback(it)
    asyncio.run(go())
    emb = it.message.edit.await_args.kwargs["embed"]
    assert "失敗" in emb.title and "IMAP 斷線" in emb.description
    it.followup.send.assert_not_awaited()


def test_每日通知每個_embed_各發一則(monkeypatch):
    posted = []
    monkeypatch.setattr(ui.config, "mail_channel_id", lambda: 123)
    monkeypatch.setattr(ui, "post_sync", lambda chan, embeds, make_view=None: posted.append((chan, embeds)))
    hs = [MailHeader(gm_msgid=str(i), uid=i, from_addr="jobs@board.example", from_name="", subject="工程師" * 30,
                     sent_date=None, labels=(), unsub=True, in_inbox=False) for i in range(100)]
    ui.notify_daily(RunReport(applied=True, job_digest=hs, promo_digest=hs))
    assert len(posted) == 3
    assert all(chan == 123 and len(embeds) == 1 for chan, embeds in posted)


def test_類別下拉_placeholder_不超過_150():
    async def go():
        item = ui.AssignSelect(7, "x" * 300)
        assert len(item.item.placeholder) <= 150 and item.item.placeholder.endswith("選類別")
    asyncio.run(go())


def test_建議卡_封數未知就不顯示():
    e = ui.suggest_embed("s3", [R(1, "news@shop.example")], {})
    assert "0 封" not in e.description and "news@shop.example" in e.description


def _patch_card(monkeypatch, rules):
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(ui, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(ui.repo, "reject", lambda db, card, ids: len(ids), raising=False)
    monkeypatch.setattr(ui.repo, "card_rules", lambda db, card: rules)
    monkeypatch.setattr(ui.repo, "rejected_rules", lambda db: [r for r in rules if r.status == "rejected"])


def test_拒絕卡上全部規則_直接發手動指定卡(monkeypatch):
    rules = [dataclasses.replace(R(1, "a@x.example"), status="rejected"),
             dataclasses.replace(R(2, "b@x.example"), status="rejected")]
    _patch_card(monkeypatch, rules)
    it = _fake_interaction(values=["1", "2"])

    async def go():
        await ui.RejectSelect("s3", [discord.SelectOption(label="a", value="1")]).callback(it)
        sent = it.followup.send.await_args.kwargs["view"]
        assert sorted(c.custom_id for c in sent.children) == ["mailrules:assign:1", "mailrules:assign:2"]
    asyncio.run(go())
    it.response.edit_message.assert_awaited_once()


def test_只拒絕部分規則_不提前發手動指定卡(monkeypatch):
    rules = [dataclasses.replace(R(1, "a@x.example"), status="rejected"), R(2, "b@x.example")]
    _patch_card(monkeypatch, rules)
    it = _fake_interaction(values=["1"])

    async def go():
        await ui.RejectSelect("s3", [discord.SelectOption(label="a", value="1")]).callback(it)
    asyncio.run(go())
    it.followup.send.assert_not_awaited()
    assert it.response.edit_message.await_args.kwargs["view"] is not None


def test_每日報告列出安全網留下的信_並截在_4096():
    hs = [MailHeader(gm_msgid=str(i), uid=i, from_addr=f"person{i}@mail.example", from_name="",
                     subject="請回覆面試時間" * 10, sent_date=None, labels=(), unsub=False, in_inbox=True)
          for i in range(300)]
    e = ui.daily_embed(RunReport(applied=True, protected=hs, unknown_patterns=2))
    assert "person0@mail.example" in e.description and "請回覆面試時間" in e.description
    assert "未知樣式：2" in e.description and len(e.description) <= 4096
    assert "還有" in e.description


def test_名單總覽與分層卡():
    ov = [{"key": "job", "title": "🛡 求職字眼", "count": 0}, {"key": "login", "title": "登入／驗證碼", "count": 3}]
    assert "求職字眼" in ui.overview_embed(ov).description and "3" in ui.overview_embed(ov).description
    assert "還沒同步過" in ui.overview_embed([dict(o, count=0) for o in ov]).description
    row = {"date": "2026-10-12", "sender": "n@bank.example", "subject": "登入通知" * 50, "where": "收件匣", "next": "10/12 丟"}
    e = ui.layer_embed({"key": "login", "title": "登入／驗證碼", "kind": "messages", "total": 300, "rows": [row] * 25}, 1, 12)
    assert "300" in e.title and len(e.description) <= 4096 and "1/12" in e.footer.text


def test_信件名單指令選項放得下():
    from mailrules.views import LAYERS
    assert len(LAYERS) <= 25 and all(len(t) <= 100 for _, t in LAYERS)
