"""重視的公司收緊：只從強求職字眼學、群發信與學校不學、新學到的網域本人確認才生效（v<N> 確認卡）；
真人判斷只認免費信箱與「名.姓」；/信件計畫 在歷史完成後仍補發確認卡。全部合成值。"""
import asyncio
import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from discordbot import mailrules_ui as ui
from mailrules import classify as C
from mailrules import repo, run
from mailrules.types import Action, MailHeader, Rule, RunReport, ValuedDomain, Verdict
from models import MailMessage, MailValuedDomain
from tests.test_mailrules_integration import UiRepo, _ix, _plans, _reminders, _wire_ui
from tests.test_mailrules_run import FakeRepo, H, T, wire

ROOT = Path(__file__).resolve().parent.parent
SELF = {"me@self-mail.example"}
COMP = {"now-corp.example"}


def hd(addr, subject, unsub=False, gid="m1"):
    return MailHeader(gm_msgid=gid, uid=1, from_addr=addr, from_name="", subject=subject,
                      sent_date=T, labels=(), unsub=unsub, in_inbox=True)


def learned(*hs):
    return set(C.learn_valued_domains(list(hs), SELF, COMP))


# ── AC1：只從強求職字眼學 ───────────────────────────────────────────

@pytest.mark.parametrize("subject", ["面試通知", "第二次面談安排", "錄取通知", "錄用通知書", "複試時間", "二面邀約",
                                     "到職須知", "聘書寄送", "聘任通知", "Interview Schedule", "Your JOB OFFER",
                                     "Offer Letter attached", "Application Status Update"])
def test_強字眼_學網域(subject):
    assert learned(hd("hr@corp-a.example", subject)) == {"corp-a.example"}


@pytest.mark.parametrize("subject", ["生日邀請函", "邀約好友", "新生報到通知", "線上測驗", "能力評量", "應徵確認",
                                     "個人資料填寫提醒", "We recruit talents", "Exclusive Offer for you"])
def test_弱字眼_不學網域_但那一封仍受第1條保護(subject):
    assert learned(hd("hr@corp-a.example", subject)) == set()
    assert C.has_job_keyword(subject)
    v = C.classify(hd("hr@corp-a.example", subject), "p", [Rule(1, "hr@corp-a.example", "*", "promo", "confirmed",
                                                                  "user")], set(), set())
    assert v == Verdict("keep_inbox", C.REASON_JOB, True)


def test_學到的網域記當初的主旨樣式():
    got = C.learn_valued_domains([hd("hr@corp-a.example", "面試 3 次")], SELF, COMP)
    assert got == {"corp-a.example": "面試 # 次"}


# ── AC2：學習排除 ──────────────────────────────────────────────────

def test_有退訂連結的群發信_不學():
    assert learned(hd("hr@corp-a.example", "面試通知", unsub=True)) == set()
    # 同網域另一封沒有退訂連結的強字眼信還是會學
    assert learned(hd("hr@corp-a.example", "面試通知", unsub=True),
                   hd("hr@corp-a.example", "錄取通知", gid="m2")) == {"corp-a.example"}


@pytest.mark.parametrize("addr", ["office@uni-a.edu", "office@mail.uni-a.edu", "office@uni-b.edu.tw",
                                  "career@dept.uni-b.edu.tw"])
def test_學校網域_不學(addr):
    assert learned(hd(addr, "面試通知")) == set()


@pytest.mark.parametrize("addr", ["a@mail.linkedin.com", "b@104.com.tw", "c@gmail.com", "d@self-mail.example",
                                  "e@hr.now-corp.example"])
def test_原有排除照舊(addr):
    assert learned(hd(addr, "面試通知")) == set()


# ── AC9：真人判斷 ──────────────────────────────────────────────────

@pytest.mark.parametrize("addr,human", [
    ("alice.wang@corp-x.example", True),
    ("bob_lin@corp-x.example", True),
    ("carol-chen-lee@corp-x.example", True),
    ("dave.wu2@corp-x.example", True),
    ("someone123@gmail.com", True),
    ("someone@yahoo.com.tw", True),
    ("no_reply@email.corp-x.example", False),
    ("no.reply@corp-x.example", False),
    ("noreply@corp-x.example", False),
    ("no-reply@corp-x.example", False),
    ("do_not_reply@corp-x.example", False),
    ("do-not-reply@corp-x.example", False),
    ("donotreply@corp-x.example", False),
    ("no_reply@gmail.com", False),
    ("hrportal@corp-x.example", False),
    ("bank@corp-x.example", False),
    ("corpx@corpx.example", False),
    ("brand-taiwan@ml.store.brand.example", False),
    ("a.wang@corp-x.example", False),
    ("ann.bo.cy.dd@corp-x.example", False),
    ("ann2.wang@corp-x.example", False),
    ("service@gmail.com", False),
    ("jane@mail.linkedin.com", False),
    ("", False),
    ("   ", False),
])
def test_真人判斷(addr, human):
    assert C.is_human(hd(addr, "週報")) is human


def test_真人判斷_有退訂連結一律不是():
    assert C.is_human(hd("alice.wang@corp-x.example", "週報", unsub=True)) is False
    assert C.is_human(hd("someone123@gmail.com", "週報", unsub=True)) is False


# ── 假 DB：依 model 分表；filter 不過濾（repo 自己要再核對） ─────────────

class Q:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return list(self.rows)
    def first(self): return self.rows[0] if self.rows else None


class DB:
    def __init__(self, domains=(), messages=()):
        self.domains, self.messages = list(domains), list(messages)
        self.added, self.deleted, self.commits = [], [], 0
    def query(self, model, *a):
        return Q(self.messages if model is MailMessage else self.domains)
    def add(self, o):
        self.added.append(o)
        self.domains.append(o)
    def delete(self, o):
        self.deleted.append(o)
        self.domains.remove(o)
    def commit(self): self.commits += 1
    def close(self): pass


def dom(domain, status="pending", card=None, posted=None, pattern="面試 #"):
    return SimpleNamespace(domain=domain, status=status, card=card, posted_at=posted, decided_at=None,
                           source_subject_pattern=pattern, first_seen=datetime(2026, 10, 1))


def mrow(addr, gone=None, trashed=None, unsub=False):
    return SimpleNamespace(from_addr=addr, gone_at=gone, trashed_at=trashed, unsub=unsub)


# ── AC4／AC5：狀態、只認確認、卡號 ─────────────────────────────────────

def test_model_欄位():
    cols = MailValuedDomain.__table__.columns
    assert {"status", "card", "posted_at", "decided_at"} <= set(cols.keys())
    assert not cols["status"].nullable and cols["status"].default.arg == "pending"


def test_main_migration_補重視網域四個欄位():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    for col, ddl in (("status", "VARCHAR DEFAULT 'pending' NOT NULL"), ("card", "VARCHAR"),
                     ("posted_at", "TIMESTAMP"), ("decided_at", "TIMESTAMP")):
        assert f'("mail_valued_domains", "{col}", "ALTER TABLE mail_valued_domains ADD COLUMN {col} {ddl}")' in src


def test_新學到的一律_pending_每張最多20個_卡號接續不重用():
    db = DB([dom("old.example", "rejected", "v3"), dom("ok.example", "confirmed", "v2")])
    new = {f"c{i:02d}.example": "面試 #" for i in range(25)}
    cards = repo.add_valued(db, dict(new, **{"old.example": "面試 #", "ok.example": "面試 #"}))
    assert cards == ["v4", "v5"]
    assert {r.domain for r in db.added} == set(new)
    assert all(r.status == "pending" for r in db.added)
    assert sum(1 for r in db.added if r.card == "v4") == 20 and sum(1 for r in db.added if r.card == "v5") == 5
    assert repo.add_valued(db, {"z.example": "面試"}) == ["v6"]
    assert repo.add_valued(db, dict(new)) == []                                   # 已有的不重開


def test_拒絕的網域永遠不再學():
    db = DB([dom("old.example", "rejected", "v1")])
    assert repo.add_valued(db, {"old.example": "面試 #"}) == [] and db.added == []
    assert db.domains[0].status == "rejected"


def test_沒卡號的舊_pending_列_強字眼還學得到的補卡_其餘刪掉():
    keep, weak = dom("keep.example"), dom("weak.example")
    db = DB([keep, weak, dom("v.example", "confirmed")])
    assert repo.add_valued(db, {"keep.example": "面試 #"}) == ["v1"]
    assert keep.card == "v1" and db.deleted == [weak] and db.added == []


def test_valued_set_只回已確認():
    db = DB([dom("p.example"), dom("c.example", "confirmed", "v1"), dom("r.example", "rejected", "v1")])
    assert repo.valued_set(db) == {"c.example"}
    assert repo.pending_valued_count(db) == 1


def test_重視公司卡_列出_未發_記已發_拒絕_確認():
    at = datetime(2026, 10, 2)
    rows = [dom("a.example", card="v1"), dom("b.example", card="v1"), dom("c.example", card="v2", posted=at),
            dom("d.example", "rejected", "v3"), dom("e.example", card="v10")]
    db = DB(rows)
    assert [d.domain for d in repo.valued_card(db, "v1")] == ["a.example", "b.example"]
    assert repo.valued_card(db, "v1")[0] == ValuedDomain("a.example", "面試 #", "pending", "v1")
    assert repo.unposted_valued_cards(db) == ["v1", "v10"]
    assert repo.pending_valued_cards(db) == ["v1", "v2", "v10"]
    repo.mark_valued_posted(db, ["v1"])
    assert rows[0].posted_at and rows[1].posted_at and repo.unposted_valued_cards(db) == ["v10"]
    assert repo.reject_valued(db, "v1", ["b.example", "c.example"]) == 1           # 別張卡的不動
    assert rows[1].status == "rejected" and rows[1].decided_at and rows[2].status == "pending"
    assert repo.confirm_valued_card(db, "v1") == 1
    assert rows[0].status == "confirmed" and rows[0].decided_at and rows[1].status == "rejected"
    assert repo.pending_valued_count(db) == 2 and repo.pending_valued_cards(db) == ["v2", "v10"]


def test_重視公司卡封數_含子網域_還在信箱():
    db = DB([dom("corp.example", card="v1"), dom("other.example", card="v1")],
            [mrow("hr@corp.example"), mrow("x@mail.corp.example"), mrow("y@corp.example", gone=datetime(2026, 1, 1)),
             mrow("z@corp.example", trashed=datetime(2026, 1, 1)), mrow("q@notcorp.example")])
    assert repo.valued_card_counts(db, "v1") == {"corp.example": 2}


def test_計畫指紋_涵蓋已確認規則與已確認網域():
    a = Rule(1, "a@x.example", "p", "promo", "confirmed", "ai", "s1")
    f = repo.plan_fingerprint
    assert f([a], set()) == repo.rules_fingerprint([a])
    assert f([a], {"b.example", "c.example"}) == f([a], {"c.example", "b.example"})
    assert len({f([a], set()), f([a], {"b.example"}), f([], {"b.example"})}) == 3


def test_confirmed_fingerprint_只看已確認網域():
    db = DB([dom("c.example", "confirmed", "v1")])
    db.query = lambda model, *a: Q([] if model is not MailValuedDomain else db.domains)
    fp = repo.confirmed_fingerprint(db)
    db.domains += [dom("p.example", card="v2"), dom("r.example", "rejected", "v2")]
    assert repo.confirmed_fingerprint(db) == fp
    db.domains[0].status = "rejected"
    assert repo.confirmed_fingerprint(db) != fp


# ── AC4／AC8：run 只讓已確認網域保護信；歷史執行把關 ────────────────────

class VRepo(FakeRepo):
    """有重視網域狀態的假 repo：domain → status。"""
    def __init__(self, doms=None):
        super().__init__()
        self.state = (1, 0, None)
        self.doms = dict(doms or {})
    def add_valued(self, db, d):
        for k in d:
            self.doms.setdefault(k, "pending")
        return []
    def valued_set(self, db): return {k for k, s in self.doms.items() if s == "confirmed"}
    def pending_valued_count(self, db): return sum(1 for s in self.doms.values() if s == "pending")
    def max_card(self, db): return None


def _real_classify_wire(monkeypatch, fake, hs):
    calls = {"apply": [], "read": []}
    monkeypatch.setattr(run, "repo", fake)
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda since: calls["read"].append(since) or (1, hs))
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: calls["apply"].append(acts) or (acts, [], []))
    monkeypatch.setattr(run.C, "builtin_suggest", lambda h, p, c: None)
    monkeypatch.setattr(run.suggest, "suggest", lambda groups: {})
    fake.store = {h.gm_msgid: h for h in hs}
    return calls


def test_只有已確認網域保護信_待確認與拒絕的不會(monkeypatch):
    fake = VRepo({"ok.example": "confirmed", "wait.example": "pending", "no.example": "rejected"})
    hs = [hd(f"hr@{d}", "資料更新提醒", gid=f"m{i}") for i, d in
          enumerate(["ok.example", "wait.example", "no.example", "mail.ok.example"])]
    _real_classify_wire(monkeypatch, fake, hs)
    run.run_daily(T, db=object())
    reasons = {g: v.reason for g, v in fake.verdicts.items()}
    assert reasons["m0"] == C.REASON_VALUED and reasons["m3"] == C.REASON_VALUED
    assert reasons["m1"] != C.REASON_VALUED and reasons["m2"] != C.REASON_VALUED


def _hist(monkeypatch, fake):
    calls = {"apply": [], "read": []}
    hs = [H("m1"), H("m2")]
    wire(monkeypatch, fake, hs, lambda h: Verdict("promo", "規則 #1", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: calls["apply"].append(acts) or (acts, [], []))
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda since: calls["read"].append(since) or (1, hs))
    fake.store = {h.gm_msgid: h for h in hs}
    return calls


def test_還有待確認網域_歷史執行零寫入拒絕(monkeypatch):
    fake = VRepo({"a.example": "pending", "b.example": "pending", "c.example": "confirmed"})
    calls = _hist(monkeypatch, fake)
    with pytest.raises(RuntimeError, match="還有 2 個重視公司沒確認"):
        run.execute_history(T, db=object(), upto_card="none", fingerprint="0123456789ab")
    assert calls["apply"] == [] and calls["read"] == [] and fake.recorded == [] and fake.state[2] is None


def test_同步後才學到新的待確認網域_仍零寫入拒絕(monkeypatch):
    fake = VRepo()
    calls = _hist(monkeypatch, fake)
    plan = run.history_plan(T, db=object())
    monkeypatch.setattr(run.C, "learn_valued_domains", lambda hs, s, c: {"late.example": "面試"})
    with pytest.raises(RuntimeError, match="還有 1 個重視公司沒確認"):
        run.execute_history(T, db=object(), upto_card=plan["upto_card"], fingerprint=plan["fingerprint"])
    assert calls["apply"] == [] and fake.recorded == [] and fake.state[2] is None


def test_history_plan_回待確認網域數_指紋含已確認網域(monkeypatch):
    fake = VRepo({"a.example": "pending", "c.example": "confirmed"})
    _hist(monkeypatch, fake)
    plan = run.history_plan(T, db=object())
    assert plan["pending_valued"] == 1
    assert plan["fingerprint"] == repo.plan_fingerprint([], {"c.example"})


def test_確認一個網域_舊計畫卡執行鈕回計畫已過期(monkeypatch):
    fake = VRepo({"a.example": "pending", "c.example": "confirmed"})
    calls = _hist(monkeypatch, fake)
    plan = run.history_plan(T, db=object())
    fake.doms["a.example"] = "confirmed"
    with pytest.raises(RuntimeError, match="計畫已過期，請用 /信件計畫 重發"):
        run.execute_history(T, db=object(), upto_card=plan["upto_card"], fingerprint=plan["fingerprint"])
    assert calls["apply"] == [] and calls["read"] == []


def test_拒絕網域或新增待確認_指紋不變(monkeypatch):
    fake = VRepo({"a.example": "pending", "c.example": "confirmed"})
    calls = _hist(monkeypatch, fake)
    plan = run.history_plan(T, db=object())
    fake.doms["a.example"] = "rejected"
    rep = run.execute_history(T, db=object(), upto_card=plan["upto_card"], fingerprint=plan["fingerprint"])
    assert rep.applied and len(calls["apply"]) == 1
    fake2 = VRepo({"c.example": "confirmed"})
    _hist(monkeypatch, fake2)
    fp = run.history_plan(T, db=object())["fingerprint"]
    fake2.doms["n.example"] = "pending"
    assert run.history_plan(T, db=object())["fingerprint"] == fp


def test_計畫卡顯示待確認重視公司():
    e = ui.history_embed({"counts": {}, "samples": {}, "pending_cards": 0, "pending_valued": 3, "unknown": 0})
    assert "待確認重視公司 3 個" in e.description


# ── AC6：Discord 重視公司確認卡 ─────────────────────────────────────

def V(d, status="pending", card="v3", pattern="面試 #"):
    return ValuedDomain(d, pattern, status, card)


def test_重視公司卡_標題_每行_footer():
    e = ui.valued_embed("v3", [V("corp-a.example"), V("corp-b.example", "rejected")], {"corp-a.example": 4})
    assert e.title == "🛡 新的重視公司：2 個網域"
    lines = e.description.split("\n")
    assert lines[0] == "corp-a.example｜面試 #｜4 封"
    assert lines[1] == "~~corp-b.example｜面試 #~~ 已拒絕"
    assert "v3" in e.footer.text and len(e.description) <= 4096


def test_重視公司卡_封數查不到就不顯示():
    e = ui.valued_embed("v3", [V("corp-a.example")], {})
    assert e.description == "corp-a.example｜面試 #"


def test_重視公司卡_custom_id_解析():
    assert ui.ValuedRejectSelect.__discord_ui_compiled_template__.fullmatch("mailrules:vreject:v12")["card"] == "v12"
    assert ui.ValuedConfirmButton.__discord_ui_compiled_template__.fullmatch("mailrules:vconfirm:v12")["card"] == "v12"
    assert ui.ValuedConfirmButton.__discord_ui_compiled_template__.fullmatch("mailrules:confirm:s12") is None

    async def go():
        v = ui.valued_view("v3", [V("a.example"), V("b.example", "rejected")])
        assert sorted(c.custom_id for c in v.children) == ["mailrules:vconfirm:v3", "mailrules:vreject:v3"]
        sel = next(c for c in v.children if c.custom_id.startswith("mailrules:vreject"))
        assert [o.value for o in sel.item.options] == ["0"]          # value＝網域依字母排序的索引，不是網域本身
        assert ui.valued_view("v3", [V("a.example", "confirmed")]) is None
    asyncio.run(go())


def test_bot_註冊重視公司卡元件():
    src = (ROOT / "discordbot" / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("add_dynamic_items("):src.index("await self.tree.sync()")]
    assert "mailrules_ui.ValuedConfirmButton" in body and "mailrules_ui.ValuedRejectSelect" in body


class CardRepo:
    def __init__(self, rows):
        self.rows, self.calls = list(rows), []
    def valued_card(self, db, card): return [r for r in self.rows if r.card == card]
    def valued_card_counts(self, db, card): return {"a.example": 3}
    def reject_valued(self, db, card, domains):
        self.calls.append(("reject", card, list(domains)))
        self.rows = [replace(r, status="rejected") if r.domain in domains and r.status == "pending" else r
                     for r in self.rows]
        return len(domains)
    def confirm_valued_card(self, db, card):
        self.calls.append(("confirm", card))
        self.rows = [replace(r, status="confirmed") if r.status == "pending" else r for r in self.rows]
        return 1


def _card_wire(monkeypatch, rows, owner="1"):
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", owner)
    monkeypatch.setattr(ui, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    fake = CardRepo(rows)
    monkeypatch.setattr(ui, "repo", fake)
    return fake


def test_非本人按不動(monkeypatch):
    fake = _card_wire(monkeypatch, [V("a.example")])
    it = _ix(uid=2)
    it.data = {"values": ["a.example"]}

    async def go():
        await ui.ValuedConfirmButton("v3").callback(it)
        await ui.ValuedRejectSelect("v3", []).callback(it)
    asyncio.run(go())
    assert fake.calls == []
    assert it.response.send_message.await_count == 2
    assert "只有卡主本人能按" in it.response.send_message.await_args.args[0]
    it.response.edit_message.assert_not_awaited()


def test_拒絕網域_卡上劃掉_還有待確認的留元件(monkeypatch):
    fake = _card_wire(monkeypatch, [V("a.example"), V("b.example")])
    it = _ix()
    it.data = {"values": ["1"]}                                      # b.example 的字母序索引

    async def go():
        await ui.ValuedRejectSelect("v3", []).callback(it)
        kw = it.response.edit_message.await_args.kwargs
        assert "~~b.example｜面試 #~~ 已拒絕" in kw["embed"].description
        assert "a.example｜面試 #｜3 封" in kw["embed"].description
        assert kw["view"] is not None
    asyncio.run(go())
    assert fake.calls == [("reject", "v3", ["b.example"])]


def test_確認後卡片最終狀態_移除元件(monkeypatch):
    fake = _card_wire(monkeypatch, [V("a.example"), V("b.example", "rejected")])
    it = _ix()

    async def go():
        await ui.ValuedConfirmButton("v3").callback(it)
    asyncio.run(go())
    assert fake.calls == [("confirm", "v3")]
    kw = it.response.edit_message.await_args.kwargs
    assert kw["view"] is None
    assert "~~b.example｜面試 #~~ 已拒絕" in kw["embed"].description
    assert "已確認" in kw["embed"].footer.text


# ── AC7：發卡接線 ──────────────────────────────────────────────────

def _vcards(sent):
    return [m.group(1) for e in sent if (m := re.match(r"信件整理 · (v\d+) ·", (e.footer.text or "") if e.footer else ""))]


def test_每日後續_重視公司卡完整發_送出才記已發(monkeypatch):
    fake = UiRepo(vpending=["v1", "v2"], vunposted=["v1", "v2"])
    sent = _wire_ui(monkeypatch, fake, ok=lambda e: "v2" not in ((e.footer.text or "") if e.footer else ""))
    ui.after_daily(RunReport(), T)
    assert _vcards(sent) == ["v1", "v2"] and fake.vmarked == ["v1"]
    assert _plans(sent) == []                                       # 有待確認網域：不發計畫卡
    sent = _wire_ui(monkeypatch, fake)                              # 下次：失敗的那張再完整發，發過的一行提醒
    ui.after_daily(RunReport(), T)
    assert _vcards(sent) == ["v2"] and fake.vmarked == ["v1", "v2"]
    assert _reminders(sent) == ["📝 還有 1 張確認卡沒處理：v1"]


def test_每日後續_發過的重視公司卡併入一行提醒(monkeypatch):
    fake = UiRepo(pending=["s3"], vpending=["v2"])
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _vcards(sent) == [] and _reminders(sent) == ["📝 還有 2 張確認卡沒處理：s3、v2"]


def test_每日後續_待確認網域還沒上卡也不發計畫卡(monkeypatch):
    fake = UiRepo(vcount=1)
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _plans(sent) == [] and fake.set_calls == []


def test_post_unposted_cards_也補發重視公司卡(monkeypatch):
    fake = UiRepo(pending=["s4"], unposted=["s4"], vpending=["v1"], vunposted=["v1"])
    sent = _wire_ui(monkeypatch, fake)
    assert ui.post_unposted_cards() == ["s4", "v1"]
    assert _vcards(sent) == ["v1"] and fake.vmarked == ["v1"]


def test_重視公司卡內容帶封數與元件(monkeypatch):
    fake = UiRepo(vpending=["v1"], vunposted=["v1"])
    fake.valued_card_counts = lambda db, card: {"v1.example": 5}
    _wire_ui(monkeypatch, fake)
    got = []
    monkeypatch.setattr(ui, "post_sync_wait",
                        lambda ch, embeds, make_view=None, timeout=30: got.append((embeds[0], make_view)) or True)
    assert ui.notify_valued_cards(["v1"]) == ["v1"]
    assert "v1.example｜面試 #｜5 封" in got[0][0].description

    async def go():
        assert sorted(c.custom_id for c in got[0][1]().children) == ["mailrules:vconfirm:v1", "mailrules:vreject:v1"]
    asyncio.run(go())


def test_重視公司卡封數查詢失敗_照發(monkeypatch):
    fake = UiRepo(vpending=["v1"], vunposted=["v1"])

    def boom(db, card):
        raise RuntimeError("DB 斷線")
    fake.valued_card_counts = boom
    sent = _wire_ui(monkeypatch, fake)
    assert ui.notify_valued_cards(["v1"]) == ["v1"] and _vcards(sent) == ["v1"]


def test_post_history_plan_一般路徑也補發重視公司卡(monkeypatch):
    fake = UiRepo(vpending=["v1"], vunposted=["v1"])
    sent = _wire_ui(monkeypatch, fake)
    msg = ui.post_history_plan(T)
    assert _vcards(sent) == ["v1"] and len(_plans(sent)) == 1 and "v1" in msg


# ── AC11：/信件計畫 在歷史完成後仍補發 ─────────────────────────────────

def test_歷史已完成_信件計畫仍補發確認卡_如實回報(monkeypatch):
    fake = UiRepo(state=(1, 0, datetime(2026, 10, 1)), pending=["s3", "s4"], unposted=["s3", "s4"],
                  vpending=["v1"], vunposted=["v1"])
    sent = _wire_ui(monkeypatch, fake, ok=lambda e: "s4" not in ((e.footer.text or "") if e.footer else ""))
    msg = ui.post_history_plan(T)
    assert _plans(sent) == []
    assert msg.startswith("歷史整理已完成，不需要計畫卡")
    assert "s3" in msg and "v1" in msg and "❌" in msg and "s4" in msg
    assert fake.marked == ["s3"] and fake.vmarked == ["v1"]


def test_歷史已完成_沒有要補發的_只回已完成(monkeypatch):
    fake = UiRepo(state=(1, 0, datetime(2026, 10, 1)))
    sent = _wire_ui(monkeypatch, fake)
    assert ui.post_history_plan(T) == "歷史整理已完成，不需要計畫卡" and sent == []
