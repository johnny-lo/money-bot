"""推銷寄件者的「任何主旨」規則、出國旅遊的內建建議、每日報告安全網那行（歷史整理完成前）、規則判 career。全部合成值。"""
from datetime import date, timedelta

import pytest

from discordbot import mailrules_ui as ui
from mailrules import classify as C
from mailrules import repo, run
from mailrules.plan import plan_actions
from mailrules.types import MailHeader, MessageState, Rule, RunReport
from models import MailRule
from tests.test_mailrules_repo import FakeSession
from tests.test_mailrules_run import FakeRepo, T


def R(rid, sender, pattern, cat="promo", status="confirmed", by="user"):
    return MailRule(id=rid, sender=sender, subject_pattern=pattern, category=cat, status=status, suggested_by=by)


class RuleDb(FakeSession):
    """add 進來的規則下一次查詢就看得到（真 DB flush 之後的行為）。"""
    def add(self, o):
        super().add(o)
        o.id = len(self.rows) + 1
        self.rows.append(o)


# ---------- ensure_promo_wildcards ----------
def test_純推銷地址補一條任何主旨_推銷_已確認():
    db = RuleDb([R(1, "news@shop.example", "電子報 #"), R(2, "news@shop.example", "週年慶")])
    assert repo.ensure_promo_wildcards(db, set()) == 1
    (w,) = db.added
    assert (w.sender, w.subject_pattern, w.category, w.status) == ("news@shop.example", "*", "promo", "confirmed")
    assert w.suggested_by == "user" and w.card is None and w.confirmed_at is not None
    assert db.commits == 1


def test_補完再呼叫一次回0_冪等():
    db = RuleDb([R(1, "news@shop.example", "電子報 #")])
    assert repo.ensure_promo_wildcards(db, set()) == 1
    assert repo.ensure_promo_wildcards(db, set()) == 0
    assert len(db.added) == 1 and db.commits == 1


def test_一次補多個地址_回傳條數():
    db = RuleDb([R(1, "a@shop.example", "x"), R(2, "b@shop.example", "x"), R(3, "c@shop.example", "x", cat="bill")])
    assert repo.ensure_promo_wildcards(db, set()) == 2
    assert sorted(w.sender for w in db.added) == ["a@shop.example", "b@shop.example"]


def test_混寄地址不補_還有別的類別():
    db = RuleDb([R(1, "news@shop.example", "電子報 #"), R(2, "news@shop.example", "訂單 #", cat="receipt")])
    assert repo.ensure_promo_wildcards(db, set()) == 0
    assert db.added == [] and db.commits == 0


@pytest.mark.parametrize("status", ["rejected", "suggested"])
def test_有被拒絕或待確認的規則不補(status):
    db = RuleDb([R(1, "news@shop.example", "電子報 #"), R(2, "news@shop.example", "別的", status=status)])
    assert repo.ensure_promo_wildcards(db, set()) == 0
    assert db.added == []


def test_只有待確認或被拒絕的推銷規則也不補():
    db = RuleDb([R(1, "a@shop.example", "x", status="suggested"), R(2, "b@shop.example", "x", status="rejected")])
    assert repo.ensure_promo_wildcards(db, set()) == 0


@pytest.mark.parametrize("sender", ["news@shop.example", "news@mail.shop.example"])
def test_重視網域含子網域不補(sender):
    db = RuleDb([R(1, sender, "電子報 #")])
    assert repo.ensure_promo_wildcards(db, {"shop.example"}) == 0
    assert db.added == []
    assert repo.ensure_promo_wildcards(db, {"other.example"}) == 1       # 別的網域重視不影響


def test_網域規則不算_也不被補():
    db = RuleDb([R(1, "@shop.example", "電子報 #")])
    assert repo.ensure_promo_wildcards(db, set()) == 0                  # 只有 @網域規則：沒有完整地址可補
    db = RuleDb([R(1, "@shop.example", "訂單 #", cat="receipt"), R(2, "news@shop.example", "電子報 #")])
    assert repo.ensure_promo_wildcards(db, set()) == 1                  # 同網域的別類 @網域規則不算這個地址的規則
    assert [w.sender for w in db.added] == ["news@shop.example"]


def test_已有任何主旨規則不重複():
    db = RuleDb([R(1, "news@shop.example", "電子報 #"), R(2, "news@shop.example", "*")])
    assert repo.ensure_promo_wildcards(db, set()) == 0
    assert db.added == []


# ---------- 每日整理 ----------
NEWS = "news@shop.example"


def wire_real(monkeypatch, fake, headers):
    for k in ("MAIL_OWNER_NAME", "MAIL_SELF_ADDRESSES", "MAIL_COMPANY_DOMAINS"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr(run, "repo", fake)
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda since: (1, headers))
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: (acts, [], []))
    monkeypatch.setattr(run.suggest, "suggest", lambda groups: {})


class WildRepo(FakeRepo):
    """規則走真的 repo.ensure_promo_wildcards（記在 RuleDb）；其餘沿用 FakeRepo。"""
    def __init__(self, rules):
        super().__init__(history_done=True)
        self.db, self.calls, self.ensure_args = RuleDb(rules), [], None

    def upsert_headers(self, db, hs, owner):
        self.calls.append("sync")
        return super().upsert_headers(db, hs, owner)

    def ensure_promo_wildcards(self, db, valued):
        self.calls.append("ensure")
        self.ensure_args = valued
        return repo.ensure_promo_wildcards(self.db, valued)

    def confirmed_rules(self, db):
        self.calls.append("rules")
        return [repo._rule(r) for r in self.db.rows if r.status == "confirmed"]

    def known_keys(self, db):
        return {(r.sender, r.subject_pattern) for r in self.db.rows}

    def save_verdicts(self, db, v):
        self.calls.append("verdicts")
        super().save_verdicts(db, v)


def mail(gid="m1", addr=NEWS, subject="新品上市 好康", unsub=False):
    return MailHeader(gm_msgid=gid, uid=int(gid[1:]), from_addr=addr, from_name="", subject=subject,
                      sent_date=T, labels=(), unsub=unsub, in_inbox=True)


def test_每日整理_只有推銷規則的地址換主旨_判推銷_不進未知(monkeypatch):
    fake = WildRepo([R(1, NEWS, "電子報 #")])
    wire_real(monkeypatch, fake, [mail()])
    rep = run.run_daily(T, db=object())
    v = fake.verdicts["m1"]
    assert (v.category, v.protected, v.reason) == ("promo", False, "規則 #2")
    assert rep.unknown_patterns == 0 and rep.new_cards == [] and fake.suggested == []
    assert rep.counts == {("promo", "archive"): 1}
    assert [(w.sender, w.subject_pattern) for w in fake.db.added] == [(NEWS, "*")]


def test_每日整理_補規則在同步之後_分類之前(monkeypatch):
    fake = WildRepo([R(1, NEWS, "電子報 #")])
    wire_real(monkeypatch, fake, [mail()])
    run.run_daily(T, db=object())
    assert fake.calls.index("sync") < fake.calls.index("ensure") < fake.calls.index("rules")
    assert fake.calls.index("ensure") < fake.calls.index("verdicts")


def test_每日整理_傳給補規則的是已確認重視網域(monkeypatch):
    fake = WildRepo([R(1, NEWS, "電子報 #")])
    fake.valued = {"corp-a.example": "p"}
    wire_real(monkeypatch, fake, [mail()])
    run.run_daily(T, db=object())
    assert fake.ensure_args == {"corp-a.example"}


def test_每日整理_混寄地址換主旨_仍是未知_不補(monkeypatch):
    fake = WildRepo([R(1, NEWS, "電子報 #"), R(2, NEWS, "訂單 #", cat="receipt")])
    wire_real(monkeypatch, fake, [mail()])
    rep = run.run_daily(T, db=object())
    assert fake.verdicts["m1"].category is None
    assert rep.unknown_patterns == 1 and fake.db.added == []


def test_每日整理_補了任何主旨規則_求職字眼的信仍被安全網留下(monkeypatch):
    fake = WildRepo([R(1, NEWS, "電子報 #")])
    wire_real(monkeypatch, fake, [mail(subject="面試通知")])
    run.run_daily(T, db=object())
    v = fake.verdicts["m1"]
    assert (v.category, v.protected, v.reason) == ("career", True, C.REASON_JOB)


# ---------- match_rule 優先序不變 ----------
def test_優先序_完整地址樣式_完整地址任何主旨_網域樣式_網域任何主旨():
    rules = [Rule(1, "@shop.example", "*", "social", "confirmed", "user"),
             Rule(2, "@shop.example", "訂單 #", "receipt", "confirmed", "user"),
             Rule(3, NEWS, "*", "promo", "confirmed", "user")]
    hh = mail(subject="訂單 1")
    assert C.match_rule(hh, "訂單 #", rules).id == 3                    # 完整地址＋'*' > 網域＋樣式
    rules.append(Rule(4, NEWS, "訂單 #", "bill", "confirmed", "user"))
    assert C.match_rule(hh, "訂單 #", rules).id == 4                    # 完整地址＋樣式 > 完整地址＋'*'
    assert C.match_rule(mail(addr="x@mail.shop.example"), "別的", rules).id == 1


# ---------- 規則判 career ----------
def test_規則判career_只加求職標籤_很舊也不移出不丟():
    rules = [Rule(5, "hr@corp-a.example", "*", "career", "confirmed", "user")]
    hh = mail(addr="hr@corp-a.example", subject="感謝您的來信", unsub=False)
    v = C.classify(hh, "感謝您的來信", rules, set(), set())
    assert (v.category, v.protected, v.reason) == ("career", False, "規則 #5")
    old = MailHeader(gm_msgid="m9", uid=9, from_addr=hh.from_addr, from_name="", subject=hh.subject,
                     sent_date=T - timedelta(days=3000), labels=(), unsub=False, in_inbox=True)
    for mode in ("daily", "history"):
        acts = plan_actions(old, v, MessageState(in_inbox=True), T, mode)
        assert [(a.kind, a.label) for a in acts] == [("label", "整理/求職")]
    done = plan_actions(old, v, MessageState(in_inbox=True, labels_applied=frozenset({"整理/求職"})), T, "daily")
    assert done == []


# ---------- builtin_suggest：出國旅遊 ----------
def sug(subject, unsub=False):
    return C.builtin_suggest(mail(subject=subject, unsub=unsub), "p", set())


@pytest.mark.parametrize("subject", ["您的航班已更改", "班機異動通知", "電子機票", "線上登機提醒",
                                     "Your flight is confirmed", "Boarding pass ready", "Flight itinerary"])
def test_內建建議_航班機票登機_是出國旅遊(subject):
    assert sug(subject) == "travel_abroad"
    assert sug(subject, unsub=True) == "travel_abroad"


@pytest.mark.parametrize("subject", ["訂房確認", "Booking confirmed", "Hotel itinerary", "明日行程提醒"])
def test_內建建議_訂房與行程_照舊是國內旅遊(subject):
    assert sug(subject) == "travel"


# ---------- daily_embed 安全網那行 ----------
def protected_hs():
    return [mail(addr="person@mail.example", subject="請回覆面試時間")]


def safety_line(rep):
    return next(x for x in ui.daily_embed(rep).description.splitlines() if x.startswith("🛡"))


def test_每日報告_已執行才提求職標籤():
    line = safety_line(RunReport(applied=True, protected=protected_hs()))
    assert "收件匣" in line and "沒移出" in line and "沒丟" in line and "整理/求職" in line and "1 封" in line


def test_每日報告_歷史整理完成前只說留在收件匣_不提求職標籤():
    rep = RunReport(applied=False, protected=protected_hs())
    line = safety_line(rep)
    assert "收件匣" in line and "沒移出" in line and "沒丟" in line and "1 封" in line
    assert "整理/求職" not in line and "求職" not in line
    assert "person@mail.example" in ui.daily_embed(rep).description
