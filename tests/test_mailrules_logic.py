from datetime import date

from mailrules import classify as C
from mailrules import config
from mailrules.patterns import subject_pattern
from mailrules.plan import plan_actions, school_label
from mailrules.types import MailHeader, MessageState, Rule, Verdict

T = date(2026, 10, 12)


def h(addr="news@shop.example", subject="週年慶", unsub=True, d=T, inbox=True):
    return MailHeader(gm_msgid="m1", uid=1, from_addr=addr, from_name="", subject=subject,
                      sent_date=d, labels=(), unsub=unsub, in_inbox=inbox)


def rule(sender, pat="*", cat="promo", status="confirmed", rid=7):
    return Rule(id=rid, sender=sender, subject_pattern=pat, category=cat, status=status, suggested_by="user")


# ---------- patterns ----------
def test_樣式_去回覆前綴_遮數字與姓名():
    assert subject_pattern("Re: RE：回覆: 王小明 2026/10/12 登入通知  ", "王小明") == "〈本人〉 #/#/# 登入通知"
    assert subject_pattern("Fwd: 訂單 12345", "") == "訂單 #"
    assert len(subject_pattern("字" * 200, "")) == 80


# ---------- safety net ----------
def test_求職字眼_任何規則都蓋不掉():
    v = C.classify(h(subject="【某公司】面談通知"), "x", [rule("news@shop.example")], set(), set())
    assert v == Verdict("keep_inbox", "主旨有求職字眼", True)
    assert C.has_job_keyword("ACME Application Status Update")


def test_重視公司_主旨不明顯也留收件匣():
    valued = {"corp-a.example"}
    v = C.classify(h("hr@corp-a.example", "個人資料提醒", unsub=False), "個人資料提醒", [], valued, set())
    assert v.category == "career" and v.protected and v.reason == "重視的公司"


def test_重視公司_只有完整地址規則能覆蓋_網域規則不行():
    valued = {"corp-a.example"}
    hh = h("careers@corp-a.example", "this job is a match", unsub=False)      # 群發信（有退訂連結）不受重視公司保護
    assert C.classify(hh, "p", [rule("@corp-a.example", cat="jobs")], valued, set()).protected
    v = C.classify(hh, "p", [rule("careers@corp-a.example", cat="jobs")], valued, set())
    assert (v.category, v.protected) == ("jobs", False)


def test_學習重視網域_排除平台_免費信箱_本人與目前公司():
    # 全部 unsub=False、被排除的都用強字眼：排除只能靠平台／免費信箱／本人／目前公司這幾條，不是被群發信或弱字眼擋掉
    hs = [h("a@corp-a.example", "面試邀請", unsub=False), h("b@mail.104.com.tw", "面試邀約", unsub=False),
          h("c@gmail.com", "面試", unsub=False), h("hr@now-corp.example", "面試通知", unsub=False),
          h("me@other.example", "錄取通知", unsub=False), h("d@corp-b.example", "一般通知", unsub=False)]
    got = C.learn_valued_domains(hs, {"me@other.example"}, {"now-corp.example"})
    assert set(got) == {"corp-a.example"}


def test_真人地址留收件匣_但確認規則可覆蓋():
    hh = h("jane.doe@corp-c.example", "週報", unsub=False)
    assert C.classify(hh, "週報", [], set(), set()) == Verdict("keep_inbox", "像真人寄的", True)
    v = C.classify(hh, "週報", [rule("jane.doe@corp-c.example", cat="company")], set(), set())
    assert (v.category, v.protected) == ("company", False)
    assert not C.is_human(h("noreply@corp-c.example", "x", unsub=False))
    assert not C.is_human(h("jane@mail.linkedin.com", "x", unsub=False))


def test_寄給自己():
    v = C.classify(h("me@other.example", "筆記", unsub=False), "筆記", [], set(), {"me@other.example"})
    assert (v.category, v.protected) == ("self", False)


def test_只認確認過的規則_優先序():
    rs = [rule("@shop.example", "*", "promo", rid=1), rule("@shop.example", "訂單 #", "receipt", rid=2),
          rule("news@shop.example", "*", "social", rid=3), rule("news@shop.example", "訂單 #", "bill", rid=4),
          rule("news@shop.example", "訂單 #", "card", status="suggested", rid=5)]
    hh = h(subject="訂單 1")
    assert C.match_rule(hh, "訂單 #", rs).id == 4
    assert C.match_rule(hh, "別的", rs).id == 3
    assert C.match_rule(h("x@mail.shop.example"), "訂單 #", rs).id == 2
    assert C.match_rule(h("x@mail.shop.example"), "別的", rs).id == 1
    assert C.classify(h("x@zzz.example"), "q", rs, set(), set()).category is None


def test_內建建議():
    S = lambda **k: C.builtin_suggest(h(**k), "p", {"now-corp.example"})
    assert S(subject="陌生裝置登入警示") == "security"
    assert S(subject="登入成功通知") == "login"
    assert S(addr="jobalerts-noreply@linkedin.com", subject="X 的工程師") == "jobs"
    assert S(addr="messages-noreply@linkedin.com", subject="有人看了你") == "social"
    assert S(addr="bulletin@mail.abc.edu.tw", subject="公告") == "school"
    assert S(addr="hr@now-corp.example", subject="考勤提醒", unsub=False) == "company"
    assert S(addr="pay@now-corp.example", subject="電子薪資條通知函", unsub=False) == "tax"
    assert S(subject="信用卡消費通知", unsub=False) == "card"
    assert S(subject="電子對帳單", unsub=False) == "bill"
    assert S(subject="您的訂單已出貨", unsub=False) == "receipt"
    assert S(subject="班機異動", unsub=False) == "travel"
    assert S(subject="本週新品") == "promo"
    assert S(subject="隨便", unsub=False) is None


# ---------- plan ----------
def st(inbox=True, labels=(), trashed=False):
    return MessageState(in_inbox=inbox, labels_applied=frozenset(labels), trashed=trashed)


def kinds(acts):
    return [(a.kind, a.label) for a in acts]


def test_學校標籤():
    assert school_label("x@mail.abc.edu.tw") == "整理/學校/abc"
    assert school_label("x@abc.edu") == "整理/學校/abc"
    assert school_label("x@foo.example") == "整理/學校"


def test_登入碼當天丟垃圾桶():
    assert kinds(plan_actions(h(d=T), Verdict("login", "r", False), st(), T, "daily")) == [("trash", None)]


def test_公司通知_30天內只移出收件匣_滿30天丟垃圾桶():
    v = Verdict("company", "r", False)
    assert kinds(plan_actions(h(d=date(2026, 9, 20)), v, st(), T, "daily")) == [("archive", None)]
    assert kinds(plan_actions(h(d=date(2026, 9, 12)), v, st(), T, "daily")) == [("trash", None)]


def test_刷卡通知_加標籤移出_滿保留天數才丟():
    v = Verdict("card", "r", False)
    assert kinds(plan_actions(h(d=date(2026, 1, 1)), v, st(), T, "daily")) == [("label", "整理/刷卡扣款"), ("archive", None)]
    old = date.fromordinal(T.toordinal() - config.FINANCE_KEEP_DAYS)
    assert kinds(plan_actions(h(d=old), v, st(labels={"整理/刷卡扣款"}), T, "daily")) == [("trash", None)]


def test_推銷_每日留14天_歷史立刻丟():
    v = Verdict("promo", "r", False)
    assert kinds(plan_actions(h(d=T), v, st(), T, "daily")) == [("archive", None)]
    assert kinds(plan_actions(h(d=T), v, st(), T, "history")) == [("trash", None)]


def test_安全警示_7天後才移出():
    v = Verdict("security", "r", False)
    assert kinds(plan_actions(h(d=date(2026, 10, 10)), v, st(), T, "daily")) == [("label", "整理/安全警示")]
    assert kinds(plan_actions(h(d=date(2026, 10, 5)), v, st(labels={"整理/安全警示"}), T, "daily")) == [("archive", None)]


def test_已做過的不重做_受保護與未知不動():
    v = Verdict("tax", "r", False)
    assert plan_actions(h(), v, st(inbox=False, labels={"整理/稅務保單"}), T, "daily") == []
    assert plan_actions(h(), Verdict("login", "r", False), st(trashed=True), T, "daily") == []
    assert plan_actions(h(), Verdict("keep_inbox", "r", True), st(), T, "daily") == []
    assert plan_actions(h(), Verdict(None, "未知", False), st(), T, "daily") == []
