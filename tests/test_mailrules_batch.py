"""每類一張整批核可卡（寄件者層的拒絕／整類確認／手動指定）、重視公司的群發信不保護、上次審查的小問題。全部合成值。"""
import asyncio
import threading
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from discordbot import mailrules_ui as ui
from mailrules import classify as C
from mailrules import repo, run, views
from mailrules.types import MailHeader, Rule, RunReport, ValuedDomain, Verdict
from models import MailMessage
from tests.test_mailrules_integration import RecSession, _ix
from tests.test_mailrules_run import FakeRepo, H, T, wire

ROOT = Path(__file__).resolve().parent.parent


# ── AC1：每類一張卡 ────────────────────────────────────────────────

def test_同類60條只開一張卡(monkeypatch):
    monkeypatch.setattr(repo, "_max_card_no", lambda db: 7)
    db = RecSession()
    cards = repo.add_suggestions(db, [(f"a{i}@x.example", "p", "promo", "ai") for i in range(60)])
    assert cards == ["s8"]
    assert len(db.added) == 60 and {r.card for r in db.added} == {"s8"} and db.commits == 1


def test_三個類別各一張卡(monkeypatch):
    monkeypatch.setattr(repo, "_max_card_no", lambda db: 0)
    db = RecSession()
    items = ([(f"p{i}@x.example", "p", "promo", "ai") for i in range(40)]
             + [(f"l{i}@x.example", "p", "login", "builtin") for i in range(30)]
             + [(f"r{i}@x.example", "p", "receipt", "ai") for i in range(2)])
    cards = repo.add_suggestions(db, items)
    assert cards == ["s1", "s2", "s3"]
    by = {}
    for r in db.added:
        by.setdefault(r.card, set()).add(r.category)
    assert by == {"s1": {"receipt"}, "s2": {"login"}, "s3": {"promo"}}


def test_連續兩次呼叫卡號遞增_不重用():
    rows = []

    class DB(RecSession):
        def add(self, o):
            super().add(o)
            rows.append(o)
    db = DB()
    db.rows = rows                                    # _max_card_no 讀得到前一次加的列
    first = repo.add_suggestions(db, [("a@x.example", "p", "promo", "ai"), ("b@x.example", "p", "login", "ai")])
    second = repo.add_suggestions(db, [("c@x.example", "p", "promo", "ai")])
    assert first == ["s1", "s2"] and second == ["s3"]


# ── AC2：卡片內容 ──────────────────────────────────────────────────

def R(i, sender, pat="本週 # 折", cat="promo", status="suggested", by="ai", card="s3"):
    return Rule(id=i, sender=sender, subject_pattern=pat, category=cat, status=status, suggested_by=by, card=card)


def test_卡片標題_寄件者行_依封數排序():
    rules = [R(1, "a@shop.example", "週報 #"), R(2, "a@shop.example", "新品"), R(3, "b@news.example")]
    counts = {("a@shop.example", "週報 #"): 3, ("a@shop.example", "新品"): 2, ("b@news.example", "本週 # 折"): 9}
    e = ui.suggest_embed("s3", rules, counts)
    assert e.title == "🤖 建議歸為『推銷／電子報』：2 個寄件者、14 封"
    assert e.description.split("\n") == ["`b@news.example`｜1 種主旨｜9 封", "`a@shop.example`｜2 種主旨｜5 封"]
    assert "s3" in e.footer.text


def test_卡片_封數查不到_不顯示封數():
    e = ui.suggest_embed("s3", [R(1, "a@shop.example"), R(2, "b@news.example")], {})
    assert e.title == "🤖 建議歸為『推銷／電子報』：2 個寄件者"
    assert e.description.split("\n") == ["`a@shop.example`｜1 種主旨", "`b@news.example`｜1 種主旨"]


def test_卡片_多類別混在一張_照舊可顯示():
    e = ui.suggest_embed("s3", [R(1, "a@shop.example"), R(2, "b@bank.example", cat="login")], {})
    assert e.title.startswith("🤖 新寄件者分類建議：2 個寄件者")


def test_卡片_超過25個寄件者_尾行指向名單():
    rules = [R(i, f"s{i:02d}@x.example") for i in range(40)]
    counts = {(f"s{i:02d}@x.example", "本週 # 折"): 100 - i for i in range(40)}
    e = ui.suggest_embed("s3", rules, counts)
    lines = e.description.split("\n")
    assert len(lines) == 26 and lines[0] == "`s00@x.example`｜1 種主旨｜100 封"
    rest = sum(100 - i for i in range(25, 40))
    assert lines[-1] == f"…還有 15 個寄件者（{rest} 封），完整名單：/信件名單 層:你的規則，或手機 PWA 📬"
    assert "40 個寄件者" in e.title


def test_卡片_超過25個寄件者_封數查不到_尾行不寫封數():
    e = ui.suggest_embed("s3", [R(i, f"s{i:02d}@x.example") for i in range(30)], {})
    assert e.description.split("\n")[-1] == "…還有 5 個寄件者，完整名單：/信件名單 層:你的規則，或手機 PWA 📬"


def test_卡片_長地址截短_不超過4096():
    rules = [R(i, f"{'x' * 900}{i:02d}@{'y' * 300}.example") for i in range(60)]
    e = ui.suggest_embed("s3", rules, {(r.sender, r.subject_pattern): 5 for r in rules})
    assert len(e.description) <= 4096 and len(e.title) <= 256
    assert all(len(line) <= 120 for line in e.description.split("\n"))


def test_卡片_被拒絕的寄件者劃掉():
    rules = [R(1, "a@shop.example", status="rejected"), R(2, "b@news.example")]
    e = ui.suggest_embed("s3", rules, {})
    assert "~~`a@shop.example`｜1 種主旨~~ 已拒絕" in e.description.split("\n")


# ── AC3：整批核可元件 ──────────────────────────────────────────────

def _opts(view):
    sel = next(c for c in view.children if c.custom_id.startswith("mailrules:rejsender:"))
    return sel.item


def test_view_一個寄件者下拉加整類確認鈕_value_是字母序索引():
    rules = [R(1, "c@x.example"), R(2, "a@x.example"), R(3, "b@x.example"), R(4, "a@x.example", "新品")]
    counts = {("b@x.example", "本週 # 折"): 9, ("c@x.example", "本週 # 折"): 5, ("a@x.example", "新品"): 1}

    async def go():
        v = ui.suggest_view("s3", rules, counts)
        assert sorted(c.custom_id for c in v.children) == ["mailrules:confirm:s3", "mailrules:rejsender:s3"]
        btn = next(c for c in v.children if c.custom_id == "mailrules:confirm:s3")
        assert btn.item.label == "✅ 整類確認"
        sel = _opts(v)
        assert [o.label for o in sel.options] == ["b@x.example", "c@x.example", "a@x.example"]   # 封數多的在前
        assert [o.value for o in sel.options] == ["1", "2", "0"]                                 # 字母序索引
        assert sel.max_values == 3
    asyncio.run(go())


def test_view_下拉只列封數最多的25個還沒決定的寄件者():
    rules = [R(i, f"s{i:02d}@x.example") for i in range(40)] + [R(99, "zz@x.example", status="rejected")]
    counts = {(r.sender, r.subject_pattern): 200 - (r.id or 0) for r in rules}

    async def go():
        sel = _opts(ui.suggest_view("s3", rules, counts))
        assert len(sel.options) == 25 and [o.label for o in sel.options][:2] == ["s00@x.example", "s01@x.example"]
        assert "zz@x.example" not in [o.label for o in sel.options]
        assert all(len(o.value) <= 100 and len(o.label) <= 100 for o in sel.options)
    asyncio.run(go())


def test_view_與callback共用_card_senders_的索引(monkeypatch):
    """發卡（下拉 value）與對回（callback）必須共用同一個 card_senders：換掉它，兩邊要一起變。"""
    rules = [R(1, "a@x.example"), R(2, "b@x.example"), R(3, "c@x.example")]
    monkeypatch.setattr(ui, "card_senders", lambda rs: sorted({r.sender for r in rs}, reverse=True))

    async def go():
        return {o.label: o.value for o in _opts(ui.suggest_view("s3", rules, {})).options}
    assert asyncio.run(go()) == {"a@x.example": "2", "b@x.example": "1", "c@x.example": "0"}


def test_custom_id_解析():
    t = ui.SenderRejectSelect.__discord_ui_compiled_template__
    assert t.fullmatch("mailrules:rejsender:s12")["card"] == "s12"
    m = ui.SenderAssignSelect.__discord_ui_compiled_template__.fullmatch("mailrules:assignsender:s12:7")
    assert (m["card"], m["idx"]) == ("s12", "7")


class BatchRepo:
    """卡上規則放記憶體；reject_senders／confirm_card／assign_sender 照 repo 的契約改狀態。"""
    def __init__(self, rules, counts=None):
        self.rules, self.counts, self.calls = list(rules), dict(counts or {}), []
    def card_rules(self, db, card): return [r for r in self.rules if r.card == card]
    def card_counts(self, db, card): return dict(self.counts)
    def reject_senders(self, db, card, senders):
        self.calls.append(("reject", card, list(senders)))
        self.rules = [replace(r, status="rejected") if r.card == card and r.sender in senders
                      and r.status == "suggested" else r for r in self.rules]
        return len(senders)
    def confirm_card(self, db, card, ids):
        self.calls.append(("confirm", card))
        self.rules = [replace(r, status="confirmed") if r.card == card and r.status == "suggested" else r
                      for r in self.rules]
        return 0, 0
    def assign_sender(self, db, card, sender, cat):
        self.calls.append(("assign", card, sender, cat))
        return 1


def _wire(monkeypatch, rules, counts=None, owner="1"):
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", owner)
    monkeypatch.setattr(ui, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    fake = BatchRepo(rules, counts)
    monkeypatch.setattr(ui, "repo", fake)
    return fake


def test_索引在封數改變後仍指向同一個寄件者(monkeypatch):
    rules = [R(1, "a@x.example"), R(2, "b@x.example"), R(3, "c@x.example")]
    async def opts_for(counts):
        return {o.label: o.value for o in _opts(ui.suggest_view("s3", rules, counts)).options}
    before = asyncio.run(opts_for({("c@x.example", "本週 # 折"): 9}))
    # 卡發出後封數變了（c 的信被丟光、a 多了很多）：卡上的 value 還是發卡當下的，callback 要對回同一個人
    fake = _wire(monkeypatch, rules, {("a@x.example", "本週 # 折"): 50})
    it = _ix()
    it.data = {"values": [before["c@x.example"]]}

    async def go():
        await ui.SenderRejectSelect("s3", []).callback(it)
    asyncio.run(go())
    assert fake.calls == [("reject", "s3", ["c@x.example"])]
    kw = it.response.edit_message.await_args.kwargs
    assert "~~`c@x.example`｜1 種主旨｜0 封~~ 已拒絕" in kw["embed"].description
    assert kw["view"] is not None


def test_勾一個寄件者_這個人卡上所有樣式都拒絕(monkeypatch):
    rules = [R(1, "a@x.example", "週報 #"), R(2, "a@x.example", "新品"), R(3, "b@x.example")]
    fake = _wire(monkeypatch, rules)
    it = _ix()
    it.data = {"values": ["0"]}
    asyncio.run(ui.SenderRejectSelect("s3", []).callback(it))
    assert fake.calls == [("reject", "s3", ["a@x.example"])]
    assert {r.id: r.status for r in fake.rules} == {1: "rejected", 2: "rejected", 3: "suggested"}


def test_非本人按不動(monkeypatch):
    fake = _wire(monkeypatch, [R(1, "a@x.example")], owner="1")
    it = _ix(uid=2)
    it.data = {"values": ["0"]}

    async def go():
        await ui.SenderRejectSelect("s3", []).callback(it)
        await ui.ConfirmButton("s3").callback(it)
        await ui.SenderAssignSelect("s3", 0, "a@x.example").callback(it)
    asyncio.run(go())
    assert fake.calls == []
    assert it.response.send_message.await_count == 3
    assert all("只有卡主本人能按" in c.args[0] for c in it.response.send_message.await_args_list)
    it.response.edit_message.assert_not_awaited()


def test_整類確認_移除元件_顯示最終狀態_發手動指定卡(monkeypatch):
    rules = [R(1, "a@x.example"), R(2, "b@x.example", status="rejected"), R(3, "b@x.example", "新品",
                                                                            status="rejected"), R(4, "c@x.example")]
    fake = _wire(monkeypatch, rules)
    it = _ix()
    asyncio.run(ui.ConfirmButton("s3").callback(it))
    assert fake.calls == [("confirm", "s3")]
    kw = it.response.edit_message.await_args.kwargs
    assert kw["view"] is None
    assert "已確認 2 個寄件者" in kw["embed"].footer.text and "拒絕 1 個" in kw["embed"].footer.text
    assert "~~`b@x.example`｜2 種主旨~~ 已拒絕" in kw["embed"].description
    views_sent = [c.kwargs["view"] for c in it.followup.send.await_args_list if c.kwargs.get("view")]
    assert len(views_sent) == 1
    assert [c.custom_id for c in views_sent[0].children] == ["mailrules:assignsender:s3:1"]   # b 是字母序第 1 個


def test_全部拒絕_最終狀態寫全部拒絕_直接發手動指定卡(monkeypatch):
    rules = [R(1, "a@x.example"), R(2, "b@x.example")]
    fake = _wire(monkeypatch, rules)
    it = _ix()
    it.data = {"values": ["0", "1"]}
    asyncio.run(ui.SenderRejectSelect("s3", []).callback(it))
    kw = it.response.edit_message.await_args.kwargs
    assert kw["view"] is None and "全部拒絕" in kw["embed"].footer.text and "已確認" not in kw["embed"].footer.text
    sent = it.followup.send.await_args.kwargs["view"]
    assert sorted(c.custom_id for c in sent.children) == ["mailrules:assignsender:s3:0", "mailrules:assignsender:s3:1"]


# ── AC4：被拒絕的寄件者手動指定 ───────────────────────────────────────

def test_手動指定卡_每則最多4個下拉_custom_id_不超過100(monkeypatch):
    long = [R(i, f"{'n' * 200}{i:02d}@x.example", status="rejected", card="s123456") for i in range(9)]
    fake = _wire(monkeypatch, long)
    it = _ix()
    asyncio.run(ui._send_assign_cards(it, "s123456", fake.rules))
    views_sent = [c.kwargs["view"] for c in it.followup.send.await_args_list]
    assert [len(v.children) for v in views_sent] == [4, 4, 1]
    for v in views_sent:
        for c in v.children:
            assert len(c.custom_id) <= 100 and len(c.item.placeholder) <= 150
            assert "keep_inbox" not in [o.value for o in c.item.options]
    assert all(len(c.args[0]) <= 2000 for c in it.followup.send.await_args_list)


def test_手動指定_依索引對回寄件者_整個人一起指定(monkeypatch):
    rules = [R(1, "b@x.example", status="rejected"), R(2, "a@x.example", status="rejected")]
    fake = _wire(monkeypatch, rules)
    it = _ix()
    it.data = {"values": ["receipt"]}
    asyncio.run(ui.SenderAssignSelect("s3", 1, "b@x.example").callback(it))
    assert fake.calls == [("assign", "s3", "b@x.example", "receipt")]
    assert "收據" in it.response.send_message.await_args.args[0]


def test_手動指定_拒絕_keep_inbox_與越界索引(monkeypatch):
    fake = _wire(monkeypatch, [R(1, "a@x.example", status="rejected")])
    it = _ix()
    it.data = {"values": ["keep_inbox"]}
    asyncio.run(ui.SenderAssignSelect("s3", 0, "a").callback(it))
    it2 = _ix()
    it2.data = {"values": ["promo"]}
    asyncio.run(ui.SenderAssignSelect("s3", 5, "a").callback(it2))
    assert fake.calls == []
    assert "⛔" in it.response.send_message.await_args.args[0]
    assert "⛔" in it2.response.send_message.await_args.args[0]


def _rows(*specs):
    return [SimpleNamespace(id=i, card=card, sender=s, subject_pattern=p, category="promo", status=st,
                            suggested_by="ai", confirmed_at=None)
            for i, (card, s, p, st) in enumerate(specs, 1)]


def test_repo_reject_senders_只動該卡該寄件者還在_suggested_的(monkeypatch):
    rows = _rows(("s3", "a@x.example", "p1", "suggested"), ("s3", "a@x.example", "p2", "suggested"),
                 ("s3", "a@x.example", "p3", "confirmed"), ("s3", "b@x.example", "p1", "suggested"),
                 ("s4", "a@x.example", "p9", "suggested"))
    db = RecSession(rows)
    assert repo.reject_senders(db, "s3", ["a@x.example"]) == 2
    assert [r.status for r in rows] == ["rejected", "rejected", "confirmed", "suggested", "suggested"]
    assert db.commits == 1


def test_repo_assign_sender_只動該卡該寄件者被拒絕的規則():
    rows = _rows(("s3", "a@x.example", "p1", "rejected"), ("s3", "a@x.example", "p2", "rejected"),
                 ("s3", "b@x.example", "p1", "rejected"), ("s4", "a@x.example", "p9", "rejected"),
                 ("s3", "a@x.example", "p3", "suggested"))
    db = RecSession(rows)
    assert repo.assign_sender(db, "s3", "a@x.example", "receipt") == 2
    assert [(r.status, r.category, r.suggested_by) for r in rows[:2]] == [("confirmed", "receipt", "user")] * 2
    assert all(r.confirmed_at for r in rows[:2])
    assert [r.status for r in rows[2:]] == ["rejected", "rejected", "suggested"]
    # 選錯了再選一次：本人指定過的那幾條改成新類別
    assert repo.assign_sender(db, "s3", "a@x.example", "bill") == 2
    assert [r.category for r in rows[:2]] == ["bill", "bill"] and rows[4].category == "promo"


def test_bot_註冊的元件與實際元件一致():
    src = (ROOT / "discordbot" / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("add_dynamic_items("):src.index("await self.tree.sync()")]
    import re
    registered = set(re.findall(r"mailrules_ui\.(\w+)", body))
    dynamic = {n for n, o in vars(ui).items()
               if isinstance(o, type) and issubclass(o, ui.discord.ui.DynamicItem) and o is not ui.discord.ui.DynamicItem}
    assert registered == dynamic
    assert {"SenderRejectSelect", "SenderAssignSelect", "ConfirmButton"} <= registered


# ── AC5：規則層搜尋比對類別名稱 ──────────────────────────────────────

def test_規則層搜尋_也比對類別名稱_待確認在前():
    rules = [{"sender": "a@shop.example", "subject_pattern": "週報", "category": "promo", "status": "confirmed",
              "suggested_by": "ai"},
             {"sender": "b@shop.example", "subject_pattern": "新品", "category": "promo", "status": "suggested",
              "suggested_by": "ai"},
             {"sender": "c@bank.example", "subject_pattern": "登入通知", "category": "login", "status": "suggested",
              "suggested_by": "builtin"}]
    out = views.build_layer("rules", [], rules, [], date(2026, 10, 13), q="推銷")
    assert [(r["sender"], r["status"]) for r in out["rows"]] == [("b@shop.example", "待確認"),
                                                                 ("a@shop.example", "已確認")]
    assert views.build_layer("rules", [], rules, [], date(2026, 10, 13), q="登入")["total"] == 1


# ── AC6：重視公司的群發信不保護 ──────────────────────────────────────

def hd(addr, subject="一般通知", unsub=False):
    return MailHeader(gm_msgid="m1", uid=1, from_addr=addr, from_name="", subject=subject, sent_date=T,
                      labels=(), unsub=unsub, in_inbox=True)


def test_同一個已確認網域_有退訂連結的不保護_沒有的保護():
    valued = {"corp-a.example"}
    rules = [Rule(7, "@corp-a.example", "*", "promo", "confirmed", "user")]
    assert C.classify(hd("hr@corp-a.example"), "一般通知", rules, valued, set()) == \
        Verdict("keep_inbox", C.REASON_VALUED, True)
    assert C.classify(hd("news@corp-a.example", unsub=True), "一般通知", rules, valued, set()) == \
        Verdict("promo", "規則 #7", False)
    # 沒有規則的群發信：照原順序往下走 → 未知（不是重視的公司）
    assert C.classify(hd("news@corp-a.example", unsub=True), "一般通知", [], valued, set()) == \
        Verdict(None, C.REASON_UNKNOWN, False)
    # 寄給自己仍在規則之前
    assert C.classify(hd("me@corp-a.example", unsub=True), "x", rules, valued, {"me@corp-a.example"}).reason == \
        C.REASON_SELF


def test_重視公司的群發信_求職字眼仍受第1條保護():
    v = C.classify(hd("news@corp-a.example", "面試邀請", unsub=True), "p", [], {"corp-a.example"}, set())
    assert v == Verdict("keep_inbox", C.REASON_JOB, True)


def test_重視公司卡封數_不含有退訂連結的信():
    from tests.test_mailrules_valued import DB, dom
    db = DB(domains=[dom("corp.example", card="v1")],
            messages=[SimpleNamespace(from_addr="hr@corp.example", gone_at=None, trashed_at=None, unsub=False),
                      SimpleNamespace(from_addr="news@corp.example", gone_at=None, trashed_at=None, unsub=True),
                      SimpleNamespace(from_addr="x@mail.corp.example", gone_at=None, trashed_at=None, unsub=False)])
    assert repo.valued_card_counts(db, "v1") == {"corp.example": 2}


def test_名單_重視公司層封數_只算沒有退訂連結的信():
    def M(sender, reason="未知", unsub=False, cat=None):
        return {"from_addr": sender, "subject": "s", "subject_pattern": "s", "sent_date": date(2026, 10, 1),
                "category": cat, "reason": reason, "in_inbox": True, "labels_applied": [], "trashed_at": None,
                "unsub": unsub}
    msgs = [M("a@wait.example"), M("b@wait.example", unsub=True), M("c@ok.example", C.REASON_VALUED, cat="keep_inbox"),
            M("d@ok.example", C.REASON_VALUED, unsub=True, cat="keep_inbox")]   # 舊判定殘留：照樣不算
    doms = [{"domain": "wait.example", "first_seen": None, "source_subject_pattern": "p", "status": "pending"},
            {"domain": "ok.example", "first_seen": None, "source_subject_pattern": "p", "status": "confirmed"}]
    out = views.build_layer("valued", msgs, [], doms, date(2026, 10, 13))
    assert [(r["domain"], r["count"]) for r in out["rows"]] == [("wait.example", 1), ("ok.example", 1)]


def test_views_load_讀_unsub():
    seen = []
    db = SimpleNamespace()
    db.query = lambda *cols: seen.append([str(c) for c in cols]) or SimpleNamespace(all=lambda: [])
    views.load(db)
    assert any(c.endswith(".unsub") for c in seen[0])


# ── AC7(a)(b)：重視公司卡 option value 用索引、最終狀態分得出全部拒絕 ─────────

def V(d, status="pending", card="v3"):
    return ValuedDomain(d, "面試 #", status, card)


def test_重視公司卡_option_value_是索引_超長網域也能發卡():
    long = "a" * 150 + ".example"
    rows = [V("b.example"), V(long), V("c.example", "rejected")]

    async def go():
        v = ui.valued_view("v3", rows)
        sel = next(c for c in v.children if c.custom_id.startswith("mailrules:vreject"))
        assert all(len(o.value) <= 100 and len(o.label) <= 100 for o in sel.item.options)
        # valued_card 依網域排序：a…(0)、b(1)、c(2)
        assert sorted(o.value for o in sel.item.options) == ["0", "1"]
    asyncio.run(go())


class VCardRepo:
    def __init__(self, rows): self.rows, self.calls = list(rows), []
    def valued_card(self, db, card): return sorted((r for r in self.rows if r.card == card), key=lambda r: r.domain)
    def valued_card_counts(self, db, card): return {}
    def reject_valued(self, db, card, domains):
        self.calls.append(("reject", card, list(domains)))
        self.rows = [replace(r, status="rejected") if r.domain in domains else r for r in self.rows]
        return len(domains)


def test_重視公司卡_用索引拒絕超長網域(monkeypatch):
    long = "a" * 150 + ".example"
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(ui, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    fake = VCardRepo([V("b.example"), V(long)])
    monkeypatch.setattr(ui, "repo", fake)
    it = _ix()
    it.data = {"values": ["0", "99"]}                 # 越界的索引忽略
    asyncio.run(ui.ValuedRejectSelect("v3", []).callback(it))
    assert fake.calls == [("reject", "v3", [long])]


def test_重視公司卡_全部拒絕_不寫已確認():
    e = ui.valued_embed("v3", [V("a.example", "rejected"), V("b.example", "rejected")], {})
    assert "全部拒絕" in e.footer.text and "已確認" not in e.footer.text
    e = ui.valued_embed("v3", [V("a.example", "confirmed"), V("b.example", "rejected")], {})
    assert "已確認 1 個" in e.footer.text and "全部拒絕" not in e.footer.text


# ── AC7(c)：執行鈕被待確認擋下 → 背景執行緒補發卡 ─────────────────────────

def _exec(monkeypatch, err, sent, want=None):
    """want＝該補發的卡（預設＝sent）、sent＝真的送出的卡。"""
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(ui.config, "mail_channel_id", lambda: 123)

    def boom(today, db=None, upto_card=None, fingerprint=None):
        raise err
    monkeypatch.setattr(run, "execute_history", boom)
    seen = {}

    def post():
        seen["thread"] = threading.get_ident()
        return list(sent if want is None else want), list(sent)
    monkeypatch.setattr(ui, "_post_unposted", post)
    it = _ix()
    asyncio.run(ui.ExecuteButton("s3", "0123456789ab").callback(it))
    return it, seen


@pytest.mark.parametrize("err", [run.PendingCards("還有 2 張確認卡沒處理"),
                                 run.PendingCards(run._VALUED_PENDING.format(1))])
def test_執行被待確認擋下_背景執行緒補發卡_說明補發了哪些(monkeypatch, err):
    it, seen = _exec(monkeypatch, err, ["s4", "v2"])
    assert seen["thread"] != threading.get_ident()                     # 經 asyncio.to_thread，不在 event loop 上
    emb = it.message.edit.await_args.kwargs["embed"]
    assert str(err) in emb.description and "s4、v2" in emb.description and "補發" in emb.description


def test_執行被待確認擋下_沒有要補發的_提示信件計畫(monkeypatch):
    it, seen = _exec(monkeypatch, run.PendingCards("還有 1 張確認卡沒處理"), [])
    assert "thread" in seen
    assert "/信件計畫" in it.message.edit.await_args.kwargs["embed"].description


def test_執行被待確認擋下_補發部分失敗_如實回報(monkeypatch):
    it, _ = _exec(monkeypatch, run.PendingCards("還有 2 張確認卡沒處理"), ["s4"], want=["s4", "v2"])
    desc = it.message.edit.await_args.kwargs["embed"].description
    assert "補發確認卡 s4" in desc and "v2 發送失敗" in desc and "都發過了" not in desc


def test_執行被待確認擋下_卡沒送出_不說都發過了(monkeypatch):
    """走真的 _post_unposted → notify_cards → post_sync_wait：Discord 沒送出（bot 沒 ready）時要如實說失敗。"""
    from tests.test_mailrules_integration import UiRepo, _wire_ui
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    _wire_ui(monkeypatch, UiRepo(pending=["s4"], unposted=["s4"]), ok=False)

    def boom(today, db=None, upto_card=None, fingerprint=None):
        raise run.PendingCards("還有 1 張確認卡沒處理")
    monkeypatch.setattr(run, "execute_history", boom)
    it = _ix()
    asyncio.run(ui.ExecuteButton("s3", "0123456789ab").callback(it))
    desc = it.message.edit.await_args.kwargs["embed"].description
    assert "s4 發送失敗" in desc and "都發過了" not in desc


def test_執行被待確認擋下_頻道沒設_如實說發不出去(monkeypatch):
    from tests.test_mailrules_integration import UiRepo, _wire_ui
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    _wire_ui(monkeypatch, UiRepo(pending=["s4"], unposted=["s4"]), chan=None)

    def boom(today, db=None, upto_card=None, fingerprint=None):
        raise run.PendingCards("還有 1 張確認卡沒處理")
    monkeypatch.setattr(run, "execute_history", boom)
    it = _ix()
    asyncio.run(ui.ExecuteButton("s3", "0123456789ab").callback(it))
    desc = it.message.edit.await_args.kwargs["embed"].description
    assert "MAIL_CHANNEL_ID" in desc and "都發過了" not in desc


def test_執行因其他原因失敗_不補發(monkeypatch):
    it, seen = _exec(monkeypatch, RuntimeError("IMAP 斷線"), ["s4"])
    assert seen == {}
    assert "IMAP 斷線" in it.message.edit.await_args.kwargs["embed"].description


def test_execute_history_待確認拒絕拋_PendingCards(monkeypatch):
    fake = FakeRepo()
    fake.pending_cards = lambda db: ["s1"]
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict("promo", "規則 #1", False), lambda h, v, m: [])
    with pytest.raises(run.PendingCards):
        run.execute_history(T, db=object())
    fake.pending_cards = lambda db: []
    fake.pending_valued_count = lambda db: 2
    with pytest.raises(run.PendingCards):
        run.execute_history(T, db=object())
    assert issubclass(run.PendingCards, RuntimeError)
