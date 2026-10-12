from datetime import date, datetime

import pytest

from mailrules import views
from mailrules.classify import REASON_HUMAN, REASON_JOB, REASON_VALUED
from mailrules.plan import next_step
from mailrules.types import MessageState

T = date(2026, 10, 13)


def M(sender="a@shop.example", subject="s", d=date(2026, 10, 1), cat=None, reason="x", inbox=True,
      labels=(), trashed=None, pattern=None):
    return {"from_addr": sender, "subject": subject, "subject_pattern": pattern or subject, "sent_date": d,
            "category": cat, "reason": reason, "in_inbox": inbox, "labels_applied": list(labels),
            "trashed_at": trashed}


def test_共19層_順序固定_下拉放得下():
    keys = [k for k, _ in views.LAYERS]
    assert len(keys) == 19 and keys[:6] == ["job", "valued", "human", "self", "rules", "unknown"]
    assert keys[-1] == "trash" and "keep_inbox" not in keys


def test_下一步_公司通知在收件匣先移出_已移出就等丟():
    d = date(2026, 10, 1)
    assert next_step("company", d, MessageState(in_inbox=True)) == ("archive", d)
    assert next_step("company", d, MessageState(in_inbox=False)) == ("trash", date(2026, 10, 31))
    assert next_step("security", d, MessageState(in_inbox=True)) == ("archive", date(2026, 10, 8))
    assert next_step("tax", d, MessageState(in_inbox=False)) is None
    assert next_step(None, d, MessageState(in_inbox=True)) is None
    assert next_step("card", d, MessageState(in_inbox=False, trashed=True)) is None


def test_保護層依理由分_類別層不含保護的信_跨年寫年份():
    msgs = [M(subject="面試通知", cat="keep_inbox", reason=REASON_JOB),
            M(subject="帳單", cat="bill", reason="規則 #1", inbox=False, labels=["整理/帳單"]),
            M(subject="hi", cat="keep_inbox", reason=REASON_HUMAN)]
    job = views.build_layer("job", msgs, [], [], T)
    assert job["kind"] == "messages" and [r["subject"] for r in job["rows"]] == ["面試通知"]
    bill = views.build_layer("bill", msgs, [], [], T)["rows"][0]
    assert bill["where"] == "資料夾" and bill["next"] == "2028/09/30 丟"
    assert views.build_layer("company", [M(cat="company", reason="規則 #2")], [], [], T)["rows"][0]["next"] == "10/01 移出"


def test_重視公司層列網域與封數():
    msgs = [M(sender="hr@corp.example", reason=REASON_VALUED, cat="keep_inbox"),
            M(sender="x@mail.corp.example", reason=REASON_VALUED, cat="keep_inbox")]
    doms = [{"domain": "corp.example", "first_seen": datetime(2026, 5, 1), "source_subject_pattern": "面試邀請"}]
    out = views.build_layer("valued", msgs, [], doms, T)
    assert out["kind"] == "domains"
    assert out["rows"] == [{"domain": "corp.example", "since": "2026-05-01", "pattern": "面試邀請", "count": 2}]


def test_未知依寄件者加樣式分組_多的在前():
    msgs = [M(sender="a@x.example", pattern="週報 #"), M(sender="a@x.example", pattern="週報 #", d=date(2026, 10, 5)),
            M(sender="b@y.example", pattern="通知")]
    out = views.build_layer("unknown", msgs, [], [], T)
    assert out["kind"] == "groups" and out["total"] == 2
    assert out["rows"][0] == {"sender": "a@x.example", "pattern": "週報 #", "count": 2, "last": "2026-10-05"}


def test_規則層_待確認排前面_中文類別與來源():
    rules = [{"sender": "@shop.example", "subject_pattern": "*", "category": "promo", "status": "confirmed",
              "suggested_by": "ai"},
             {"sender": "n@bank.example", "subject_pattern": "登入通知", "category": "login", "status": "suggested",
              "suggested_by": "builtin"}]
    out = views.build_layer("rules", [], rules, [], T)
    assert [r["status"] for r in out["rows"]] == ["待確認", "已確認"]
    assert out["rows"][1]["category"] == "推銷／電子報" and out["rows"][1]["by"] == "AI"


def test_垃圾桶層只列30天內_附救得回期限():
    msgs = [M(subject="舊", trashed=datetime(2026, 9, 1), cat="promo"),
            M(subject="新", trashed=datetime(2026, 10, 10), cat="promo")]
    out = views.build_layer("trash", msgs, [], [], T)
    assert [r["subject"] for r in out["rows"]] == ["新"] and out["rows"][0]["next"] == "11/09 前救得回"
    assert views.build_layer("promo", msgs, [], [], T)["total"] == 0


def test_搜尋不分大小寫_分頁():
    msgs = [M(sender=f"s{i}@x.example", subject=f"訂單 {i}", cat="receipt", d=date(2026, 10, 1 + i % 9))
            for i in range(30)]
    out = views.build_layer("receipt", msgs, [], [], T, q="S1", offset=0, limit=5)
    assert out["total"] == 11 and len(out["rows"]) == 5          # s1、s10–s19
    assert len(views.build_layer("receipt", msgs, [], [], T, offset=25, limit=10)["rows"]) == 5


def test_未知的層_KeyError():
    with pytest.raises(KeyError):
        views.build_layer("nope", [], [], [], T)


def test_總覽每層一筆():
    ov = views.overview_from([M(cat="login", reason="規則 #2")], [], [], T)
    assert len(ov) == 19 and {o["key"]: o["count"] for o in ov}["login"] == 1


def test_信件API都要token():
    from auth import require_token
    from routes.mail import router
    paths = {r.path: r for r in router.routes}
    assert set(paths) == {"/api/mail/overview", "/api/mail/layers/{key}"}
    for r in paths.values():
        assert any(d.call is require_token for d in r.dependant.dependencies)


def test_信件名單指令註冊_層選項來自LAYERS_頁與搜尋有預設():
    from types import SimpleNamespace

    import discord
    from discord import app_commands

    from discordbot.commands import register_commands
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    register_commands(SimpleNamespace(tree=tree))
    cmd = tree.get_command("信件名單")
    params = {p.name: p for p in cmd.parameters}
    assert set(params) == {"層", "頁", "搜尋"}
    assert [c.value for c in params["層"].choices] == [k for k, _ in views.LAYERS]
    assert not params["層"].required and params["頁"].default == 1 and params["搜尋"].default == ""


def test_下一步_兩個期限都過了_每日模式直接丟_和plan_actions一致():
    d = date(2026, 9, 1)                                  # company：當天移出、30 天後丟 → 10/01 起已到丟的期限
    st = MessageState(in_inbox=True)
    assert next_step("company", d, st, today=T) == ("trash", date(2026, 10, 1))
    assert next_step("company", d, st, today=date(2026, 9, 20)) == ("archive", d)   # 還沒到丟的期限：仍先移出
    assert next_step("company", d, st) == ("archive", d)                            # 不帶 today：舊行為
    assert next_step("company", d, MessageState(in_inbox=False, trashed=True), today=T) is None


def test_名單_很舊還在收件匣的信_下一步是丟不是過去日期的移出():
    old = M(d=date(2026, 9, 1), cat="company", reason="規則 #2")
    assert views.build_layer("company", [old], [], [], T)["rows"][0]["next"] == "10/01 丟"


def _呼叫信件名單(monkeypatch, user_id, owner):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import discord
    from discord import app_commands

    from discordbot.commands import register_commands
    if owner is None:
        monkeypatch.delenv("AUTOFIX_OWNER_USER_ID", raising=False)
    else:
        monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", str(owner))
    monkeypatch.setattr(views, "overview", lambda db, today: [{"key": "job", "title": "🛡 求職字眼", "count": 2}])
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    register_commands(SimpleNamespace(tree=tree))
    ix = MagicMock()
    ix.user.id = user_id
    ix.response.defer = AsyncMock()
    ix.response.send_message = AsyncMock()
    ix.followup.send = AsyncMock()
    asyncio.run(tree.get_command("信件名單").callback(ix))
    return ix


@pytest.mark.parametrize("owner", [None, 111])
def test_信件名單指令不限本人_沒設卡主或不是卡主都能看(monkeypatch, owner):
    ix = _呼叫信件名單(monkeypatch, user_id=222, owner=owner)
    ix.response.send_message.assert_not_awaited()
    ix.response.defer.assert_awaited_once_with(ephemeral=True)
    assert ix.followup.send.await_args.kwargs["ephemeral"] is True
    assert "求職字眼" in ix.followup.send.await_args.kwargs["embed"].description
