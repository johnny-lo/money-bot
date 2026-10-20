"""career（求職）：由安全網或 DB 裡直接指定的規則判定（AI 建議、Discord 手動指定不提供）；留收件匣、只加「整理/求職」標籤。
全部合成值。"""
import asyncio
import json
from datetime import date

import pytest

from discordbot import mailrules_ui as ui
from mailrules import classify as C
from mailrules import config, suggest, views
from mailrules.plan import next_step, plan_actions
from mailrules.types import MailHeader, MessageState, Rule, Verdict
from tests.test_mailrules_batch import R, _wire
from tests.test_mailrules_integration import _ix

T = date(2026, 10, 13)
VALUED = {"corp-a.example"}


def hd(addr="hr@corp-a.example", subject="一般通知", unsub=False, d=T, inbox=True):
    return MailHeader(gm_msgid="m1", uid=1, from_addr=addr, from_name="", subject=subject, sent_date=d,
                      labels=(), unsub=unsub, in_inbox=inbox)


def st(inbox=True, labels=(), trashed=False):
    return MessageState(in_inbox=inbox, labels_applied=frozenset(labels), trashed=trashed)


def kinds(acts):
    return [(a.kind, a.label) for a in acts]


# ── AC1：設定 ──────────────────────────────────────────────────────

def test_類別順序_career緊接在keep_inbox之後():
    assert [k for k, _ in config.CATEGORIES][:2] == ["keep_inbox", "career"]
    assert config.LABELS["career"] == "求職"


def test_career保留期限_只有標籤():
    r = config.RETENTION["career"]
    assert r.label == f"{config.LABEL_ROOT}/求職" == "整理/求職"
    assert r.archive_after_days is None and r.trash_after_days is None and r.digest is None


def test_強求職字眼都在求職字眼清單裡():
    # classify 只在「主旨有求職字眼」時才看強字眼：強字眼若不在清單裡，那種主旨連第 1 條安全網都碰不到
    for s in ["面試通知", "第二次面談安排", "錄取通知", "錄用通知書", "複試時間", "二面邀約", "到職須知", "聘書寄送",
              "聘任通知", "Interview Schedule", "Your JOB OFFER", "Offer Letter attached", "Application Status Update"]:
        assert C.has_strong_job_keyword(s) and C.has_job_keyword(s), s


# ── AC2：classify ─────────────────────────────────────────────────

def test_強字眼_非群發_不論網域_都是career():
    v = C.classify(hd("someone@board.example", "面試邀請通知"), "p", [], set(), set())
    assert v == Verdict("career", C.REASON_JOB, True)


def test_弱字眼_非群發_重視網域_是career():
    v = C.classify(hd("hr@corp-a.example", "活動邀請"), "p", [], VALUED, set())
    assert v == Verdict("career", C.REASON_JOB, True)
    v = C.classify(hd("hr@mail.corp-a.example", "新生報到通知"), "p", [], VALUED, set())     # 子網域也算
    assert v == Verdict("career", C.REASON_JOB, True)


def test_弱字眼_非群發_非重視網域_留keep_inbox():
    v = C.classify(hd("hr@corp-b.example", "活動邀請"), "p", [], VALUED, set())
    assert v == Verdict("keep_inbox", C.REASON_JOB, True)
    v = C.classify(hd("hr@corp-b.example", "活動邀請"), "p", [], set(), set())
    assert v == Verdict("keep_inbox", C.REASON_JOB, True)


@pytest.mark.parametrize("addr", ["hr@corp-a.example", "hr@corp-b.example"])
def test_強字眼_有退訂連結_留keep_inbox(addr):
    v = C.classify(hd(addr, "面試邀請通知", unsub=True), "p", [], VALUED, set())
    assert v == Verdict("keep_inbox", C.REASON_JOB, True)


def test_弱字眼_有退訂連結_重視網域_也留keep_inbox():
    v = C.classify(hd("hr@corp-a.example", "活動邀請", unsub=True), "p", [], VALUED, set())
    assert v == Verdict("keep_inbox", C.REASON_JOB, True)


def test_重視網域_非群發_無字眼_是career_理由是重視的公司():
    v = C.classify(hd("hr@corp-a.example", "個人資料提醒"), "p", [], VALUED, set())
    assert v == Verdict("career", C.REASON_VALUED, True)


def test_重視網域_被完整地址規則覆蓋_照規則走():
    rules = [Rule(9, "careers@corp-a.example", "*", "jobs", "confirmed", "user")]
    v = C.classify(hd("careers@corp-a.example", "職缺配對"), "p", rules, VALUED, set())
    assert (v.category, v.protected, v.reason) == ("jobs", False, "規則 #9")


def test_重視網域_網域規則蓋不掉_仍是career():
    rules = [Rule(9, "@corp-a.example", "*", "promo", "confirmed", "user")]
    v = C.classify(hd("hr@corp-a.example", "個人資料提醒"), "p", rules, VALUED, set())
    assert v == Verdict("career", C.REASON_VALUED, True)


def test_求職字眼_完整地址規則也蓋不掉_仍是career():
    rules = [Rule(9, "hr@corp-a.example", "*", "promo", "confirmed", "user")]
    v = C.classify(hd("hr@corp-a.example", "面試通知"), "p", rules, VALUED, set())
    assert v == Verdict("career", C.REASON_JOB, True)


def test_真人分支照舊_keep_inbox():
    v = C.classify(hd("jane.doe@corp-c.example", "週報"), "週報", [], set(), set())
    assert v == Verdict("keep_inbox", C.REASON_HUMAN, True)


def test_REASON字串不變():
    assert (C.REASON_JOB, C.REASON_VALUED, C.REASON_HUMAN) == ("主旨有求職字眼", "重視的公司", "像真人寄的")


# ── AC3：plan_actions ─────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["daily", "history"])
@pytest.mark.parametrize("sent", [T, date(2020, 1, 1)])      # 後者早於任何保留天數
def test_career_只加標籤_不移出不丟(mode, sent):
    v = Verdict("career", C.REASON_JOB, True)
    assert kinds(plan_actions(hd(d=sent), v, st(), T, mode)) == [("label", "整理/求職")]
    assert plan_actions(hd(d=sent), v, st(labels={"整理/求職"}), T, mode) == []


@pytest.mark.parametrize("mode", ["daily", "history"])
def test_career_已不在收件匣也只加標籤(mode):
    v = Verdict("career", C.REASON_VALUED, True)
    assert kinds(plan_actions(hd(d=date(2020, 1, 1)), v, st(inbox=False), T, mode)) == [("label", "整理/求職")]


@pytest.mark.parametrize("mode", ["daily", "history"])
def test_keep_inbox_保護判定回空清單(mode):
    for sent in (T, date(2020, 1, 1)):
        assert plan_actions(hd(d=sent), Verdict("keep_inbox", C.REASON_JOB, True), st(), T, mode) == []


@pytest.mark.parametrize("mode", ["daily", "history"])
@pytest.mark.parametrize("cat", ["card", "company", "promo", "login", "security"])
def test_任何protected判定都絕不產生archive或trash(mode, cat):
    old = date(2020, 1, 1)                                   # 超過每一種保留天數
    acts = plan_actions(hd(d=old), Verdict(cat, "r", True), st(), T, mode)
    assert {a.kind for a in acts} <= {"label"}
    assert plan_actions(hd(d=old), Verdict(cat, "r", True), st(labels={config.RETENTION[cat].label}), T, mode) == []


def test_career_已丟垃圾桶不規劃():
    assert plan_actions(hd(), Verdict("career", C.REASON_JOB, True), st(trashed=True), T, "daily") == []


def test_沒保護的類別照舊():
    assert kinds(plan_actions(hd(d=date(2020, 1, 1)), Verdict("card", "r", False), st(), T, "daily")) == [
        ("label", "整理/刷卡扣款"), ("trash", None)]


# ── AC4：AI 建議與 Discord 手動指定不提供 career ──────────────────

def test_AI建議_enum與prompt都不含career(monkeypatch):
    seen = {}

    def fake(prompt, schema=None):
        seen["prompt"], seen["schema"] = prompt, schema
        return json.dumps({"items": [{"i": 0, "category": "career", "why": "x"},
                                     {"i": 1, "category": "login", "why": "x"}]})
    monkeypatch.setattr(suggest, "codex_text", fake)
    groups = [{"sender": "a@x.example", "name": "", "pattern": "p", "subjects": ["p"], "count": 1},
              {"sender": "b@x.example", "name": "", "pattern": "q", "subjects": ["q"], "count": 1}]
    assert suggest.suggest(groups) == {("b@x.example", "q"): "login"}        # AI 回 career → 忽略
    enum = seen["schema"]["properties"]["items"]["items"]["properties"]["category"]["enum"]
    assert "career" not in enum and "keep_inbox" not in enum and "promo" in enum
    assert "career" not in seen["prompt"] and "求職" not in seen["prompt"]


def test_手動指定下拉不提供career():
    async def go():
        for item in (ui.AssignSelect(7, "x").item, ui.SenderAssignSelect("s3", 0, "a").item):
            vals = [o.value for o in item.options]
            assert "career" not in vals and "keep_inbox" not in vals and "promo" in vals
    asyncio.run(go())
    assert [o.value for o in ui._assign_options()].count("career") == 0


def test_手動指定_career被拒絕(monkeypatch):
    assert ui._valid_category(["career"]) is None and ui._valid_category(["promo"]) == "promo"
    fake = _wire(monkeypatch, [R(1, "a@x.example", status="rejected")])
    it = _ix()
    it.data = {"values": ["career"]}
    asyncio.run(ui.SenderAssignSelect("s3", 0, "a").callback(it))
    assert fake.calls == []
    assert "⛔" in it.response.send_message.await_args.args[0]


# ── AC5：next_step 與名單檢視 ─────────────────────────────────────

def test_next_step_career沒有下一步():
    d = date(2020, 1, 1)
    assert next_step("career", d, MessageState(in_inbox=True)) is None
    assert next_step("career", d, MessageState(in_inbox=True), T) is None
    assert next_step("career", d, MessageState(in_inbox=False, labels_applied=frozenset({"整理/求職"})), T) is None


def M(sender="a@shop.example", subject="s", d=date(2026, 10, 1), cat=None, reason="x", inbox=True,
      labels=(), unsub=False):
    return {"from_addr": sender, "subject": subject, "subject_pattern": subject, "sent_date": d, "category": cat,
            "reason": reason, "in_inbox": inbox, "labels_applied": list(labels), "trashed_at": None, "unsub": unsub}


def test_名單_兩個保護層照舊依reason列_求職層依category列():
    msgs = [M(subject="面試通知", cat="career", reason=C.REASON_JOB, labels=["整理/求職"]),
            M(subject="活動邀請", cat="keep_inbox", reason=C.REASON_JOB),
            M(sender="hr@corp-a.example", subject="個資提醒", cat="career", reason=C.REASON_VALUED,
              labels=["整理/求職"]),
            M(subject="hi", cat="keep_inbox", reason=C.REASON_HUMAN)]
    job = views.build_layer("job", msgs, [], [], T)
    assert [r["subject"] for r in job["rows"]] == ["面試通知", "活動邀請"]
    doms = [{"domain": "corp-a.example", "first_seen": None, "source_subject_pattern": "p", "status": "confirmed"}]
    assert views.build_layer("valued", msgs, [], doms, T)["rows"][0]["count"] == 1
    career = views.build_layer("career", msgs, [], [], T)
    assert career["title"] == "求職" and career["kind"] == "messages" and career["total"] == 2
    assert {r["subject"] for r in career["rows"]} == {"面試通知", "個資提醒"}
    assert all(r["where"] == "收件匣" and r["next"] is None for r in career["rows"])
    human = views.build_layer("human", msgs, [], [], T)
    assert [r["subject"] for r in human["rows"]] == ["hi"]


def test_名單_求職層在總覽_且不含keep_inbox():
    keys = [k for k, _ in views.LAYERS]
    assert "career" in keys and "keep_inbox" not in keys and len(keys) == 21 and len(keys) <= 25
    ov = {o["key"]: o["count"] for o in views.overview_from(
        [M(cat="career", reason=C.REASON_JOB), M(cat="keep_inbox", reason=C.REASON_JOB)], [], [], T)}
    assert ov["career"] == 1 and ov["job"] == 2
