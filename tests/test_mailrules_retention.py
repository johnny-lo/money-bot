"""帳單不刪、旅遊分出國／國內的保留期限，與每日報告卡安全網那一行。全部合成值。"""
import asyncio
import json
from datetime import date, timedelta

import pytest

from discordbot import mailrules_ui as ui
from mailrules import config, suggest
from mailrules.plan import next_step, plan_actions
from mailrules.types import MailHeader, MessageState, RunReport, Verdict

T = date(2026, 10, 12)
VERY_OLD = T - timedelta(days=2000)


def hd(d=T, inbox=True):
    return MailHeader(gm_msgid="m1", uid=1, from_addr="news@shop.example", from_name="", subject="通知",
                      sent_date=d, labels=(), unsub=True, in_inbox=inbox)


def st(inbox=True, labels=(), trashed=False):
    return MessageState(in_inbox=inbox, labels_applied=frozenset(labels), trashed=trashed)


def kinds(acts):
    return [(a.kind, a.label) for a in acts]


# ---------- 設定 ----------
def test_保留期限_只有金融兩類滾動兩年():
    R = config.RETENTION
    assert R["card"].trash_after_days == R["receipt"].trash_after_days == config.FINANCE_KEEP_DAYS == 730
    assert R["bill"].trash_after_days is None and R["bill"].archive_after_days == 0
    assert R["bill"].label == "整理/帳單" and R["bill"].digest is None


def test_旅遊分兩類_出國不丟_國內照舊():
    keys = [k for k, _ in config.CATEGORIES]
    assert keys.index("travel_abroad") == keys.index("travel") + 1
    assert config.LABELS["travel_abroad"] == "出國旅遊" and config.LABELS["travel"] == "國內旅遊／交通"
    assert config.RETENTION["travel_abroad"] == config.Retention(label="整理/出國旅遊", archive_after_days=0)
    assert config.RETENTION["travel"] == config.Retention(label="整理/旅遊", archive_after_days=0, trash_after_days=180)
    assert "travel_abroad" not in config.SAFETY_NET_ONLY


# ---------- plan_actions ----------
@pytest.mark.parametrize("mode", ["daily", "history"])
def test_帳單很舊也不丟_只加標籤移出(mode):
    v = Verdict("bill", "r", False)
    assert kinds(plan_actions(hd(d=VERY_OLD), v, st(), T, mode)) == [("label", "整理/帳單"), ("archive", None)]
    assert kinds(plan_actions(hd(d=VERY_OLD), v, st(labels={"整理/帳單"}), T, mode)) == [("archive", None)]
    assert plan_actions(hd(d=VERY_OLD), v, st(inbox=False, labels={"整理/帳單"}), T, mode) == []
    assert kinds(plan_actions(hd(d=T - timedelta(days=config.FINANCE_KEEP_DAYS)), v, st(), T, mode)) == [
        ("label", "整理/帳單"), ("archive", None)]


@pytest.mark.parametrize("mode", ["daily", "history"])
def test_出國旅遊很舊也不丟_只加標籤移出(mode):
    v = Verdict("travel_abroad", "r", False)
    assert kinds(plan_actions(hd(d=VERY_OLD), v, st(), T, mode)) == [("label", "整理/出國旅遊"), ("archive", None)]
    assert plan_actions(hd(d=VERY_OLD), v, st(inbox=False, labels={"整理/出國旅遊"}), T, mode) == []


def test_國內旅遊_滿180天照舊丟():
    v = Verdict("travel", "r", False)
    assert kinds(plan_actions(hd(d=T - timedelta(days=179)), v, st(), T, "daily")) == [
        ("label", "整理/旅遊"), ("archive", None)]
    assert kinds(plan_actions(hd(d=T - timedelta(days=180)), v, st(labels={"整理/旅遊"}), T, "daily")) == [
        ("trash", None)]


def test_刷卡與收據照舊_滿兩年丟():
    old = T - timedelta(days=config.FINANCE_KEEP_DAYS)
    for cat, lab in (("card", "整理/刷卡扣款"), ("receipt", "整理/收據")):
        assert kinds(plan_actions(hd(d=old), Verdict(cat, "r", False), st(labels={lab}), T, "daily")) == [
            ("trash", None)]


# ---------- next_step ----------
@pytest.mark.parametrize("cat", ["bill", "travel_abroad"])
def test_下一步_不丟的類別不回trash(cat):
    assert next_step(cat, VERY_OLD, st(inbox=True), today=T) == ("archive", VERY_OLD)
    assert next_step(cat, VERY_OLD, st(inbox=False), today=T) is None
    assert next_step(cat, VERY_OLD, st(inbox=False)) is None


def test_下一步_國內旅遊與刷卡仍會丟():
    d = date(2026, 1, 1)
    assert next_step("travel", d, st(inbox=False)) == ("trash", d + timedelta(days=180))
    assert next_step("card", d, st(inbox=False)) == ("trash", d + timedelta(days=config.FINANCE_KEEP_DAYS))


# ---------- AI 建議與手動指定 ----------
def test_AI建議_travel_abroad是一般類別(monkeypatch):
    seen = {}

    def fake(prompt, schema=None):
        seen["prompt"], seen["schema"] = prompt, schema
        return json.dumps({"items": [{"i": 0, "category": "travel_abroad", "why": "x"}]})
    monkeypatch.setattr(suggest, "codex_text", fake)
    groups = [{"sender": "a@x.example", "name": "", "pattern": "p", "subjects": ["p"], "count": 1}]
    assert suggest.suggest(groups) == {("a@x.example", "p"): "travel_abroad"}
    enum = seen["schema"]["properties"]["items"]["items"]["properties"]["category"]["enum"]
    assert "travel_abroad" in enum and "travel" in enum
    assert "- travel_abroad：出國旅遊" in seen["prompt"] and "- travel：國內旅遊／交通" in seen["prompt"]


def test_手動指定下拉_有出國旅遊_且指定得了():
    async def go():
        for item in (ui.AssignSelect(7, "x").item, ui.SenderAssignSelect("s3", 0, "a").item):
            opts = {o.value: o.label for o in item.options}
            assert opts["travel_abroad"] == "出國旅遊" and opts["travel"] == "國內旅遊／交通"
            assert len(opts) <= 25
    asyncio.run(go())
    assert ui._valid_category(["travel_abroad"]) == "travel_abroad"


# ---------- 每日報告卡 ----------
def test_每日報告安全網那行_說清楚留在收件匣_求職另加標籤():
    hs = [MailHeader(gm_msgid="1", uid=1, from_addr="person@mail.example", from_name="", subject="請回覆面試時間",
                     sent_date=None, labels=(), unsub=False, in_inbox=True)]
    desc = ui.daily_embed(RunReport(applied=True, protected=hs)).description
    assert "我沒動" not in desc
    line = next(x for x in desc.splitlines() if x.startswith("🛡"))
    assert "收件匣" in line and "整理/求職" in line and "1 封" in line
    assert "person@mail.example" in desc


def test_每日報告沒有安全網的信_不出現那行():
    assert "🛡" not in ui.daily_embed(RunReport(applied=True)).description
