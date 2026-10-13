"""信件規則引擎整合修正：歷史計畫卡自動發、執行鈕帶卡號與規則指紋、消失的信、斷線不丟紀錄、
unsub／顯示名稱存 DB、migration、並行保護、確認卡分類分卡與封數、確認卡逐卡記已發、小修。"""
import asyncio
import re
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from discordbot import bridge
from discordbot import mailrules_ui as ui
from mailrules import classify as C
from mailrules import config, gmail_rw, repo, run, views
from mailrules.gmail_rw import apply as _real_apply
from mailrules.repo import card_no
from mailrules.run import history_plan as _real_history_plan
from mailrules.types import Action, MailHeader, MessageState, Rule, RunReport, Verdict
from models import MailMessage, MailRule, MailState
from tests.test_mailrules_gmail import FakeM
from tests.test_mailrules_run import FakeRepo, H, T, wire

ROOT = Path(__file__).resolve().parent.parent
FP = "0123456789ab"


# ── 共用假物件 ─────────────────────────────────────────────────────

class RecQuery:
    """記下 filter 條件的假 query（FakeSession 不會真的過濾，所以把條件字串化來驗）。"""
    def __init__(self, rows, log): self.rows, self.log = rows, log
    def filter(self, *a, **k):
        self.log += [str(x) for x in a]
        return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None


class RecSession:
    def __init__(self, rows=()):
        self.rows, self.added, self.commits, self.filters = list(rows), [], 0, []
    def query(self, *a, **k): return RecQuery(self.rows, self.filters)
    def add(self, o): self.added.append(o)
    def commit(self): self.commits += 1
    def close(self): pass


def row(gid, **kw):
    base = dict(gm_msgid=gid, uid=1, from_addr="a@shop.example", from_name=None, subject="s",
                subject_pattern="s", sent_date=T, in_inbox=True, labels_applied=[], trashed_at=None,
                gone_at=None, unsub=False)
    base.update(kw)
    return SimpleNamespace(**base)


class SearchM(FakeM):
    """假 IMAP，UID SEARCH X-GM-MSGID 依 search_map（預設＝msgids 反查）回 uid。"""
    def __init__(self, search_map=None, fetch_boom_at=None, **kw):
        super().__init__(**kw)
        self.search_map, self.fetch_boom_at, self._fetches = search_map, fetch_boom_at, 0

    def uid(self, cmd, *args):
        if cmd == "SEARCH" and args[:1] == ("X-GM-MSGID",):
            self.calls.append(("uid", cmd) + args)
            if self.search_map is not None:
                hit = self.search_map.get(args[1], [])
            else:
                hit = [u for u, g in self.msgids.items() if g == args[1]]
            return "OK", [" ".join(map(str, hit)).encode()]
        if cmd == "FETCH" and args[1] == "(X-GM-MSGID)":
            self._fetches += 1
            if self._fetches == self.fetch_boom_at:
                self.calls.append(("uid", cmd) + args)
                raise OSError("連線被重設")
        return super().uid(cmd, *args)


def _ix(uid=1):
    return SimpleNamespace(
        user=SimpleNamespace(id=uid, display_name="本人"), data={"values": []},
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()), message=SimpleNamespace(edit=AsyncMock()))


# ── AC1：歷史計畫卡自動發、/信件計畫 ──────────────────────────────────

def test_mail_state_有_plan_posted_card_欄位():
    assert "plan_posted_card" in MailState.__table__.columns.keys()
    assert MailState.__table__.columns["plan_posted_card"].nullable


class UiRepo:
    """mailrules_ui 用到的 repo 假物件：待確認卡、哪些卡還沒成功發過、已確認規則指紋都放記憶體。"""
    def __init__(self, state=(1, 0, None), pending=(), unposted=(), max_card="s7", posted=None, fp="f1"):
        self.state, self.pending, self.unposted = state, list(pending), list(unposted)
        self.max, self.posted, self.fp = max_card, posted, fp
        self.set_calls, self.marked = [], []
    def get_state(self, db): return self.state
    def pending_cards(self, db): return list(self.pending)
    def unposted_cards(self, db): return [c for c in self.pending if c in self.unposted]
    def mark_cards_posted(self, db, cards):
        self.marked += list(cards)
        self.unposted = [c for c in self.unposted if c not in cards]
    def max_card(self, db): return self.max
    def confirmed_fingerprint(self, db): return self.fp
    def plan_posted_card(self, db): return self.posted
    def set_plan_posted(self, db, fp):
        self.set_calls.append(fp)
        self.posted = fp
    def card_rules(self, db, card):
        return [Rule(id=card_no(card), sender=f"{card}@x.example", subject_pattern="p", category="promo",
                     status="suggested", suggested_by="ai", card=card)]
    def card_counts(self, db, card): return {}


def _wire_ui(monkeypatch, fake, ok=True, chan=123):
    """只把 Discord 發送層換成假的 post_sync_wait（ok＝送出結果；可給 embed → bool 的函式），其餘走真的 mailrules_ui。"""
    sent = []
    monkeypatch.setattr(ui, "SessionLocal", lambda: RecSession())
    monkeypatch.setattr(ui, "repo", fake)
    monkeypatch.setattr(ui.config, "mail_channel_id", lambda: chan)
    monkeypatch.setattr(run, "history_plan", lambda today, db=None: {
        "counts": {}, "samples": {}, "pending_cards": len(fake.pending), "unknown": 0,
        "upto_card": fake.max, "fingerprint": fake.fp})

    def wait(ch, embeds, make_view=None, timeout=30):
        sent.append(embeds[0])
        return ok(embeds[0]) if callable(ok) else ok
    monkeypatch.setattr(ui, "post_sync_wait", wait)
    monkeypatch.setattr(ui, "post_sync", lambda ch, embeds, make_view=None: sent.append(embeds[0]))
    return sent


def _plans(sent):
    return [e for e in sent if "歷史信件整理計畫" in (e.title or "")]


def _cards(sent):
    return [m.group(1) for e in sent if (m := re.match(r"信件整理 · (s\d+) ·", e.footer.text or ""))]


def _reminders(sent):
    return [e.description for e in sent if "張確認卡沒處理" in (e.description or "")]


def test_每日後續_歷史未完成_無待確認卡_沒發過_自動發計畫卡_送出成功才記指紋(monkeypatch):
    fake = UiRepo(fp="f1", posted=None)
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert len(_plans(sent)) == 1 and fake.set_calls == ["f1"]


def test_每日後續_計畫卡送失敗_不記已發_隔天再發(monkeypatch):
    fake = UiRepo(fp="f1", posted=None)
    sent = _wire_ui(monkeypatch, fake, ok=False)
    ui.after_daily(RunReport(), T)
    assert len(_plans(sent)) == 1 and fake.set_calls == [] and fake.posted is None
    ui.after_daily(RunReport(), T)
    assert len(_plans(sent)) == 2 and fake.set_calls == []


def test_每日後續_bot_沒_ready_不記已發(monkeypatch):
    fake = UiRepo(fp="f1", posted=None)
    _wire_ui(monkeypatch, fake)
    monkeypatch.setattr(ui, "post_sync_wait", bridge.post_sync_wait)       # 走真的 bridge
    for bot in (None, SimpleNamespace(loop=SimpleNamespace(is_closed=lambda: False), is_ready=lambda: False)):
        monkeypatch.setattr(bridge, "_bot_instance", bot)
        ui.after_daily(RunReport(), T)
    assert fake.set_calls == [] and fake.posted is None


def test_每日後續_頻道沒設_什麼都不發也不標記(monkeypatch):
    fake = UiRepo(pending=["s3"], unposted=["s3"])
    sent = _wire_ui(monkeypatch, fake, chan=None)
    ui.after_daily(RunReport(new_cards=["s3"]), T)
    assert sent == [] and fake.marked == [] and fake.set_calls == []
    fake = UiRepo()
    sent = _wire_ui(monkeypatch, fake, chan=None)
    ui.after_daily(RunReport(), T)
    assert sent == [] and fake.set_calls == []


def test_每日後續_同一套已確認規則的計畫發過了_不重發(monkeypatch):
    fake = UiRepo(fp="f1", posted="f1")
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _plans(sent) == [] and fake.set_calls == []


def test_每日後續_已確認規則集合變了_重發新計畫(monkeypatch):
    fake = UiRepo(fp="f2", posted="f1")
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert len(_plans(sent)) == 1 and fake.set_calls == ["f2"]
    ui.after_daily(RunReport(), T)
    assert len(_plans(sent)) == 1


def test_每日後續_有待確認卡_或歷史已完成_不發計畫卡(monkeypatch):
    fake = UiRepo(pending=["s3"])
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _plans(sent) == []
    fake = UiRepo(state=(1, 0, datetime(2026, 10, 1)))
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _plans(sent) == []


def test_每日後續_另一個整理正在跑_不發計畫卡也不中斷(monkeypatch):
    fake = UiRepo(fp="f1", posted=None)
    sent = _wire_ui(monkeypatch, fake)
    monkeypatch.setattr(run, "history_plan", _real_history_plan)
    assert run._LOCK.acquire(blocking=False)
    try:
        ui.after_daily(RunReport(), T)
    finally:
        run._LOCK.release()
    assert _plans(sent) == [] and fake.set_calls == []


def test_信件計畫指令_任何人都能發_計畫卡到頻道(monkeypatch):
    from discordbot import commands
    reg = {}
    tree = SimpleNamespace(command=lambda **kw: (lambda f: reg.setdefault(kw["name"], f)))
    commands.register_commands(SimpleNamespace(tree=tree))
    assert "信件計畫" in reg
    called = []
    monkeypatch.setattr(ui, "post_history_plan", lambda today: called.append(today) or "✅ 已發到信件頻道")
    it = _ix(uid=999)                                  # 不是本人也能下指令
    asyncio.run(reg["信件計畫"](it))
    assert len(called) == 1
    assert "已發" in it.followup.send.await_args.args[0]


def test_post_history_plan_發過也照發_送出成功才記指紋(monkeypatch):
    fake = UiRepo(fp="f1", posted="f1")
    sent = _wire_ui(monkeypatch, fake)
    msg = ui.post_history_plan(T)
    assert len(_plans(sent)) == 1 and fake.set_calls == ["f1"] and "已發" in msg


def test_post_history_plan_送失敗_如實回報_不記已發(monkeypatch):
    fake = UiRepo(fp="f1", posted=None)
    sent = _wire_ui(monkeypatch, fake, ok=False)
    msg = ui.post_history_plan(T)
    assert len(_plans(sent)) == 1 and fake.set_calls == [] and fake.posted is None
    assert "失敗" in msg and "✅" not in msg and "已發到" not in msg


def test_post_history_plan_歷史已完成_不發(monkeypatch):
    fake = UiRepo(state=(1, 0, datetime(2026, 10, 1)))
    sent = _wire_ui(monkeypatch, fake)
    msg = ui.post_history_plan(T)
    assert _plans(sent) == [] and "已完成" in msg


def test_post_history_plan_搶不到鎖_回另一個信件整理正在跑(monkeypatch):
    fake = UiRepo(pending=["s3"], unposted=["s3"])
    sent = _wire_ui(monkeypatch, fake)
    monkeypatch.setattr(run, "history_plan", _real_history_plan)       # 真的 history_plan：鎖在 DB 之前
    assert run._LOCK.acquire(blocking=False)
    try:
        msg = ui.post_history_plan(T)
    finally:
        run._LOCK.release()
    assert "另一個信件整理正在跑" in msg and _plans(sent) == [] and fake.set_calls == []


def test_post_history_plan_順便完整重發還沒發出過的待確認卡(monkeypatch):
    fake = UiRepo(pending=["s3", "s5"], unposted=["s5"])
    sent = _wire_ui(monkeypatch, fake)
    msg = ui.post_history_plan(T)
    assert _cards(sent) == ["s5"] and fake.marked == ["s5"] and len(_plans(sent)) == 1
    assert "已發" in msg


def test_post_history_plan_確認卡送失敗_如實回報_不標記(monkeypatch):
    fake = UiRepo(pending=["s5"], unposted=["s5"])
    _wire_ui(monkeypatch, fake, ok=lambda e: "歷史信件整理計畫" in (e.title or ""))
    msg = ui.post_history_plan(T)
    assert fake.marked == [] and "s5" in msg and "失敗" in msg


def test_執行中訊息_寫明可用信件計畫重發(monkeypatch):
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(run, "execute_history",
                        lambda today, db=None, upto_card=None, fingerprint=None: RunReport(applied=True))
    it = _ix()
    asyncio.run(ui.ExecuteButton("s7", FP).callback(it))
    desc = it.response.edit_message.await_args.kwargs["embed"].description
    assert "若停在這裡，可用 /信件計畫 重發計畫卡" in desc


def test_mail_daily_呼叫每日後續_出錯也補發還沒發出的確認卡():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    body = src[src.index("def _mail_daily"):src.index("scheduler.add_job(_mail_daily")]
    assert "after_daily(" in body
    assert "post_unposted_cards(" in body[body.index("except Exception"):]


# ── AC2／AC11：執行鈕帶卡號與已確認規則指紋、只被舊卡擋、規則變了就過期 ─────────

def test_執行鈕_custom_id_帶卡號與規則指紋():
    tpl = ui.ExecuteButton.__discord_ui_compiled_template__
    m = tpl.fullmatch(f"mailrules:exec:history:s7:{FP}")
    assert (m["card"], m["fp"]) == ("s7", FP)
    m = tpl.fullmatch(f"mailrules:exec:history:none:{FP}")
    assert (m["card"], m["fp"]) == ("none", FP)

    async def go():
        assert ui.ExecuteButton("s7", FP).item.custom_id == f"mailrules:exec:history:s7:{FP}"
        assert ui.ExecuteButton("none", FP).item.custom_id == f"mailrules:exec:history:none:{FP}"
        assert len(ui.ExecuteButton("s99999", "f" * 12).item.custom_id) <= 100
    asyncio.run(go())


def test_計畫卡的執行鈕用計畫裡的卡號與指紋_回報是否送出(monkeypatch):
    got = []
    monkeypatch.setattr(ui.config, "mail_channel_id", lambda: 123)
    monkeypatch.setattr(ui, "post_sync_wait",
                        lambda ch, embeds, make_view=None, timeout=30: got.append(make_view) or True)
    plan = {"counts": {}, "samples": {}, "pending_cards": 0, "unknown": 0, "upto_card": "s4", "fingerprint": FP}
    assert ui.notify_history_plan(plan) is True

    async def go():
        v = got[0]()
        assert [c.custom_id for c in v.children] == [f"mailrules:exec:history:s4:{FP}"]
    asyncio.run(go())
    monkeypatch.setattr(ui, "post_sync_wait", lambda ch, embeds, make_view=None, timeout=30: False)
    assert ui.notify_history_plan(plan) is False


def _hist_repo(pending):
    fake = FakeRepo()
    fake.state = (1, 0, None)
    fake.pending_cards = lambda db: list(pending)
    return fake


def test_execute_history_只被不大於_upto_的卡擋(monkeypatch):
    fake = _hist_repo(["s3", "s9"])
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict("promo", "規則", False), lambda h, v, m: [])
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: (acts, [], []))
    with pytest.raises(RuntimeError, match="確認卡"):
        run.execute_history(T, db=object(), upto_card="s5")
    fake.pending_cards = lambda db: ["s9", "s12"]
    rep = run.execute_history(T, db=object(), upto_card="s5")
    assert rep.applied and fake.state[2] == "done"


def test_execute_history_upto_none_不被後長的卡擋(monkeypatch):
    fake = _hist_repo(["s1"])
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict("promo", "規則", False), lambda h, v, m: [])
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: (acts, [], []))
    assert run.execute_history(T, db=object(), upto_card="none").applied


def test_execute_history_沒給_upto_維持原本行為(monkeypatch):
    fake = _hist_repo(["s9"])
    monkeypatch.setattr(run, "repo", fake)
    with pytest.raises(RuntimeError, match="確認卡"):
        run.execute_history(T, db=object())


def test_執行鈕把卡號與指紋傳給_execute_history(monkeypatch):
    seen = []
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(run, "execute_history", lambda today, db=None, upto_card=None, fingerprint=None:
                        seen.append((upto_card, fingerprint)) or RunReport(applied=True))
    asyncio.run(ui.ExecuteButton("s7", FP).callback(_ix()))
    assert seen == [("s7", FP)]


def test_沒帶規則指紋的舊執行鈕_不執行_回計畫已過期(monkeypatch):
    seen = []
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(run, "execute_history", lambda *a, **k: seen.append(k) or RunReport(applied=True))
    it = _ix()
    asyncio.run(ui.ExecuteButton("s7").callback(it))
    assert seen == []
    assert "計畫已過期，請用 /信件計畫 重發" in it.response.send_message.await_args.args[0]


def test_執行失敗_重編訊息把同一顆執行鈕帶回來(monkeypatch):
    def boom(today, db=None, upto_card=None, fingerprint=None):
        raise RuntimeError("還有 1 張確認卡沒處理")
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(run, "execute_history", boom)
    it = _ix()
    asyncio.run(ui.ExecuteButton("s7", FP).callback(it))
    kw = it.message.edit.await_args.kwargs
    assert "失敗" in kw["embed"].title
    assert [c.custom_id for c in kw["view"].children] == [f"mailrules:exec:history:s7:{FP}"]


class RuleRepo(FakeRepo):
    """有規則表的假 repo：確認卡、手動指定都會改變已確認規則集合。"""
    def __init__(self):
        super().__init__()
        self.state = (1, 0, None)
        self.rules = [Rule(1, "a@shop.example", "s", "promo", "confirmed", "ai", "s1"),
                      Rule(2, "c@shop.example", "s", "promo", "rejected", "ai", "s1")]
    def confirmed_rules(self, db): return [r for r in self.rules if r.status == "confirmed"]
    def pending_cards(self, db): return sorted({r.card for r in self.rules if r.status == "suggested"}, key=card_no)
    def max_card(self, db): return max((r.card for r in self.rules), key=card_no, default=None)
    def known_keys(self, db): return {(r.sender, r.subject_pattern) for r in self.rules}
    def new_card(self, card, rid, sender):
        self.rules.append(Rule(rid, sender, "s", "promo", "suggested", "ai", card))
    def confirm(self, card):
        self.rules = [replace(r, status="confirmed") if r.card == card and r.status == "suggested" else r
                      for r in self.rules]
    def assign(self, rid, category):
        self.rules = [replace(r, status="confirmed", category=category, suggested_by="user") if r.id == rid else r
                      for r in self.rules]


def _hist_wire(monkeypatch, fake):
    calls = {"apply": [], "read": []}
    hs = [H("m1"), H("m2")]
    wire(monkeypatch, fake, hs, lambda h: Verdict("promo", "規則 #1", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: calls["apply"].append(acts) or (acts, [], []))
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda since: calls["read"].append(since) or (1, hs))
    fake.store = {h.gm_msgid: h for h in hs}
    return calls


def test_history_plan_帶發卡當下的已確認規則指紋(monkeypatch):
    fake = RuleRepo()
    _hist_wire(monkeypatch, fake)
    plan = run.history_plan(T, db=object())
    assert plan["fingerprint"] == repo.rules_fingerprint(fake.confirmed_rules(None))
    assert plan["upto_card"] == "s1"


@pytest.mark.parametrize("change", ["確認新卡", "手動指定"])
def test_發計畫後_確認卡或手動指定規則_按舊執行鈕_拒絕且零寫入(monkeypatch, change):
    fake = RuleRepo()
    calls = _hist_wire(monkeypatch, fake)
    plan = run.history_plan(T, db=object())
    if change == "確認新卡":
        fake.new_card("s2", 3, "b@shop.example")
        fake.confirm("s2")
    else:
        fake.assign(2, "login")
    calls["read"].clear()
    with pytest.raises(RuntimeError, match="計畫已過期，請用 /信件計畫 重發"):
        run.execute_history(T, db=object(), upto_card=plan["upto_card"], fingerprint=plan["fingerprint"])
    assert calls["apply"] == [] and calls["read"] == [] and fake.recorded == [] and fake.state[2] is None


def test_發計畫後才長出的未確認卡_不擋_也不讓計畫過期(monkeypatch):
    fake = RuleRepo()
    calls = _hist_wire(monkeypatch, fake)
    plan = run.history_plan(T, db=object())
    fake.new_card("s2", 3, "b@shop.example")                  # 之後才長出、還沒處理
    rep = run.execute_history(T, db=object(), upto_card=plan["upto_card"], fingerprint=plan["fingerprint"])
    assert rep.applied and len(calls["apply"]) == 1 and fake.state[2] == "done"


def test_按舊執行鈕_規則變了_訊息說計畫已過期_零寫入(monkeypatch):
    fake = RuleRepo()
    calls = _hist_wire(monkeypatch, fake)

    @contextmanager
    def no_db(db):
        yield object()
    monkeypatch.setattr(run, "_session", no_db)
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    plan = run.history_plan(T)
    fake.new_card("s2", 3, "b@shop.example")
    fake.confirm("s2")
    it = _ix()
    asyncio.run(ui.ExecuteButton(plan["upto_card"], plan["fingerprint"]).callback(it))
    emb = it.message.edit.await_args.kwargs["embed"]
    assert "失敗" in emb.title and "計畫已過期，請用 /信件計畫 重發" in emb.description
    assert calls["apply"] == [] and fake.recorded == []


def test_規則指紋_只看已確認規則集合():
    a = Rule(1, "a@x.example", "p", "promo", "confirmed", "ai", "s1")
    b = Rule(2, "b@x.example", "p", "login", "confirmed", "user", "s2")
    f = repo.rules_fingerprint
    assert f([a, b]) == f([b, a]) and re.fullmatch(r"[0-9a-f]{12}", f([]))
    assert len({f([]), f([a]), f([a, b]), f([a, replace(b, category="promo")])}) == 4


# ── AC3：消失的信 ───────────────────────────────────────────────────

def test_apply_uid_變了_用_msgid_找到新_uid_再核對後寫入(monkeypatch):
    M = SearchM(msgids={11: "1001", 30: "1002"})
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    done, failed, gone = gmail_rw.apply([Action("1002", 12, "trash")], expected_uidvalidity=42)
    assert done == [Action("1002", 30, "trash")] and failed == [] and gone == []
    i_search = next(i for i, c in enumerate(M.calls) if c[:3] == ("uid", "SEARCH", "X-GM-MSGID"))
    i_verify = next(i for i, c in enumerate(M.calls) if c[:2] == ("uid", "FETCH") and c[2] == "30")
    i_write = next(i for i, c in enumerate(M.calls) if c in M.writes())
    assert i_search < i_verify < i_write
    assert M.calls[i_write][2] == "30"


def test_apply_所有郵件找不到_回報_gone_不寫(monkeypatch):
    M = SearchM(msgids={11: "1001"})
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    acts = [Action("1002", 12, "label", "整理/收據"), Action("1002", 12, "trash")]
    done, failed, gone = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == [] and failed == [] and gone == acts and M.writes() == []


def test_apply_換_uid_後再核對不符_不寫_進_failed(monkeypatch):
    M = SearchM(msgids={11: "1001", 30: "9999"}, search_map={"1002": [30]})
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    done, failed, gone = gmail_rw.apply([Action("1002", 12, "trash")], expected_uidvalidity=42)
    assert done == [] and gone == [] and failed == [Action("1002", 12, "trash")]
    assert M.writes() == []


class FlakyM(SearchM):
    """查詢暫時失敗的假 IMAP：UID SEARCH X-GM-MSGID 回 NO／BAD 或拋例外、核對用的 UID FETCH 回 NO。"""
    def __init__(self, search_typ=None, search_boom=False, fetch_typ=None, **kw):
        super().__init__(**kw)
        self.search_typ, self.search_boom, self.fetch_typ = search_typ, search_boom, fetch_typ

    def uid(self, cmd, *args):
        if cmd == "SEARCH" and args[:1] == ("X-GM-MSGID",) and (self.search_typ or self.search_boom):
            self.calls.append(("uid", cmd) + args)
            if self.search_boom:
                raise OSError("讀取逾時")
            return self.search_typ, [b"temporary failure"]
        if cmd == "FETCH" and args[1] == "(X-GM-MSGID)" and self.fetch_typ:
            self.calls.append(("uid", cmd) + args)
            return self.fetch_typ, [b"temporary failure"]
        return super().uid(cmd, *args)


@pytest.mark.parametrize("kw", [dict(search_typ="NO"), dict(search_typ="BAD"), dict(search_boom=True),
                                dict(fetch_typ="NO")],
                         ids=["SEARCH回NO", "SEARCH回BAD", "SEARCH拋例外", "核對FETCH回NO"])
def test_暫時查詢失敗不算消失_進_failed_零寫入_gone_為空(monkeypatch, kw):
    # 1002 的 uid 對不上、所有郵件也搜不到：查詢若被當成成功，就會被誤判成 gone
    M = FlakyM(msgids={11: "1001"}, search_map={}, **kw)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    acts = [Action("1001", 11, "label", "整理/收據"), Action("1002", 12, "trash")]
    done, failed, gone = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == [] and failed == acts and gone == [] and M.writes() == []


def test_守衛_SEARCH_只用來查_X_GM_MSGID():
    src = Path(gmail_rw.__file__).read_text(encoding="utf-8")
    assert '"SEARCH", "X-GM-MSGID"' in src
    for bad in ("\\Deleted", "M.expunge(", "M.append(", "M.copy(", "BODY[]"):
        assert bad not in src


def test_run_gone_的信記進_DB_不算失敗(monkeypatch):
    fake = FakeRepo(history_done=True)
    fake.gone = []
    fake.mark_gone = lambda db, ids: fake.gone.extend(ids)
    wire(monkeypatch, fake, [H("m1"), H("m2")], lambda h: Verdict("login", "規則 #1", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "label", "整理/x"), Action(h.gm_msgid, h.uid, "trash")])
    monkeypatch.setattr(run.gmail_rw, "apply",
                        lambda acts: ([a for a in acts if a.gm_msgid == "m1"], [],
                                      [a for a in acts if a.gm_msgid == "m2"]))
    rep = run.run_daily(T, db=object())
    assert rep.failed == 0 and rep.gone == 1 and fake.gone == ["m2"]
    assert len(fake.recorded) == 2


def test_mail_messages_有_gone_at_unsub_from_name():
    cols = MailMessage.__table__.columns
    assert cols["gone_at"].nullable
    assert not cols["unsub"].nullable and cols["unsub"].default.arg is False
    assert cols["from_name"].nullable


def test_mark_gone_寫入_gone_at():
    rows = [row("a"), row("b")]
    db = RecSession(rows)
    repo.mark_gone(db, ["a"])
    assert rows[0].gone_at is not None and rows[1].gone_at is None and db.commits == 1


def test_headers_與_messages_排除_gone():
    db = RecSession([row("a")])
    repo.headers(db)
    assert any("gone_at IS NULL" in f for f in db.filters)


def test_重新同步看到的信_清掉_gone_at():
    r = row("a", gone_at=datetime(2026, 10, 1))
    db = RecSession([r])
    repo.upsert_headers(db, [replace(H("m9"), gm_msgid="a", uid=77)], "")
    assert r.gone_at is None and r.uid == 77


def test_名單不列出_gone_的信():
    def M(gone=None, **kw):
        base = {"from_addr": "a@x.example", "subject": "s", "subject_pattern": "s", "sent_date": date(2026, 10, 1),
                "category": None, "reason": "未知", "in_inbox": True, "labels_applied": [], "trashed_at": None,
                "gone_at": gone}
        base.update(kw)
        return base
    msgs = [M(), M(gone=datetime(2026, 10, 2)), M(category="promo", reason="規則 #1"),
            M(category="promo", reason="規則 #1", gone=datetime(2026, 10, 2))]
    assert views.build_layer("unknown", msgs, [], [], T)["rows"][0]["count"] == 1
    assert views.build_layer("promo", msgs, [], [], T)["total"] == 1
    ov = {x["key"]: x["count"] for x in views.overview_from(msgs, [], [], T)}
    assert ov["unknown"] == 1 and ov["promo"] == 1


def test_views_load_讀_gone_at():
    seen = []
    db = SimpleNamespace()
    db.query = lambda *cols: seen.append([str(c) for c in cols]) or SimpleNamespace(all=lambda: [])
    views.load(db)
    assert any(c.endswith(".gone_at") for c in seen[0])


def test_每日報告卡顯示已不在信箱():
    e = ui.daily_embed(RunReport(applied=True, gone=3))
    assert "已不在信箱 3 封（略過）" in e.description


# ── AC4：寫到一半出錯不丟紀錄 ───────────────────────────────────────

ACTS4 = [Action("1001", 11, "trash"), Action("1002", 12, "trash"),
         Action("1003", 13, "trash"), Action("1004", 14, "trash")]
IDS4 = {11: "1001", 12: "1002", 13: "1003", 14: "1004"}


def test_apply_第二批核對拋例外_第一批照常回傳_第二批進_failed(monkeypatch):
    M = SearchM(msgids=dict(IDS4), fetch_boom_at=2)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    monkeypatch.setattr(gmail_rw, "CHUNK", 2)
    done, failed, gone = gmail_rw.apply(ACTS4, expected_uidvalidity=42)
    assert done == ACTS4[:2] and failed == ACTS4[2:] and gone == []


def test_run_第二批_UID_FETCH_拋_OSError_第一批已寫入的都記進_DB(monkeypatch):
    fake = FakeRepo()
    fake.state = (42, 0, None)
    hs = [replace(H(f"m{u}"), gm_msgid=g) for u, g in IDS4.items()]
    wire(monkeypatch, fake, hs, lambda h: Verdict("login", "規則 #1", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda since: (42, hs))
    M = SearchM(msgids=dict(IDS4), fetch_boom_at=2)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    monkeypatch.setattr(gmail_rw, "CHUNK", 2)
    monkeypatch.setattr(gmail_rw, "_stored_uidvalidity", lambda: 42)
    monkeypatch.setattr(run.gmail_rw, "apply", _real_apply)       # wire() 換成假的，這裡要真的 apply
    rep = run.execute_history(T, db=object())
    assert [a.gm_msgid for a in fake.recorded] == ["1001", "1002"]
    assert rep.failed == 2


# ── AC5：unsub／顯示名稱存 DB ───────────────────────────────────────

def test_upsert_headers_寫入_unsub_與_from_name():
    db = RecSession()
    h = replace(H("m1"), from_name="Shop 電子報", unsub=True)
    repo.upsert_headers(db, [h], "")
    assert db.added[0].unsub is True and db.added[0].from_name == "Shop 電子報"
    r = row("m2")
    repo.upsert_headers(RecSession([r]), [replace(H("m2"), from_name="X", unsub=True)], "")
    assert r.unsub is True and r.from_name == "X"


def test_headers_讀回_unsub_與_from_name():
    hs = repo.headers(RecSession([row("a", unsub=True, from_name="Jane")]))
    assert hs[0].unsub is True and hs[0].from_name == "Jane"
    hs = repo.headers(RecSession([row("b", unsub=None, from_name=None)]))
    assert hs[0].unsub is False and hs[0].from_name == ""


def test_不是本次同步的電子報_每日分類仍是未知_不會變成像真人寄的(monkeypatch):
    # 電子報寄件地址看起來像個人（jane@），只有 List-Unsubscribe 能分辨
    news = MailHeader(gm_msgid="m1", uid=1, from_addr="jane@brand.example", from_name="Jane",
                      subject="本週精選", sent_date=T, labels=(), unsub=True, in_inbox=True)
    add = RecSession()
    repo.upsert_headers(add, [news], "")
    stored = add.added[0]
    stored.gone_at, stored.trashed_at = None, None
    later = RecSession([stored])                      # 隔天：沒有新信，只能從 DB 讀回
    fresh, verdicts = [], {}
    monkeypatch.setattr(run, "repo", SimpleNamespace(
        headers=lambda db: repo.headers(later), add_valued=lambda db, d: None, valued_set=lambda db: set(),
        confirmed_rules=lambda db: [], save_verdicts=lambda db, v: verdicts.update(v)))
    run._classify_all(object(), T, fresh)
    assert verdicts["m1"].category is None and verdicts["m1"].reason != C.REASON_HUMAN


# ── AC6：既有表補欄位 ──────────────────────────────────────────────

def test_main_migration_補五個欄位():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "ALTER TABLE mail_messages ADD COLUMN gone_at TIMESTAMP" in src
    assert "ALTER TABLE mail_messages ADD COLUMN unsub BOOLEAN DEFAULT FALSE NOT NULL" in src
    assert "ALTER TABLE mail_messages ADD COLUMN from_name VARCHAR" in src
    assert "ALTER TABLE mail_state ADD COLUMN plan_posted_card VARCHAR" in src
    assert "ALTER TABLE mail_rules ADD COLUMN posted_at TIMESTAMP" in src
    for tbl, col in (("mail_messages", "gone_at"), ("mail_messages", "unsub"), ("mail_messages", "from_name"),
                     ("mail_state", "plan_posted_card"), ("mail_rules", "posted_at")):
        assert f'("{tbl}", "{col}", "ALTER TABLE {tbl} ADD COLUMN {col} ' in src
    assert 'print(f"✅ 已自動新增 {_tbl}.{_col} 欄位")' in src


def test_mail_rules_有_posted_at_欄位():
    assert MailRule.__table__.columns["posted_at"].nullable


# ── AC7：並行保護 ──────────────────────────────────────────────────

def test_有模組層鎖():
    import threading
    assert isinstance(run._LOCK, type(threading.Lock()))


def test_搶不到鎖_每日略過_不寫入不拋例外(monkeypatch):
    fake = FakeRepo(history_done=True)
    reads = []
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict("login", "規則 #1", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda since: reads.append(since) or (1, [H("m1")]))
    assert run._LOCK.acquire(blocking=False)
    try:
        rep = run.run_daily(T, db=object())
    finally:
        run._LOCK.release()
    assert rep.skipped and not rep.applied and reads == [] and fake.recorded == []
    rep = run.run_daily(T, db=object())                # 鎖放掉後照常跑
    assert rep.applied and not rep.skipped


def test_搶不到鎖_歷史準備與執行拋_RuntimeError(monkeypatch):
    monkeypatch.setattr(run, "repo", FakeRepo())
    assert run._LOCK.acquire(blocking=False)
    try:
        for fn in (run.prepare_history, run.execute_history, run.history_plan):
            with pytest.raises(RuntimeError, match="另一個信件整理正在跑"):
                fn(T, db=object())
    finally:
        run._LOCK.release()


def test_出錯也會放掉鎖(monkeypatch):
    fake = FakeRepo()
    fake.pending_cards = lambda db: ["s1"]
    monkeypatch.setattr(run, "repo", fake)
    with pytest.raises(RuntimeError):
        run.execute_history(T, db=object())
    assert run._LOCK.acquire(blocking=False)
    run._LOCK.release()


def test_每日報告卡_略過時說明():
    assert "另一個信件整理正在跑" in ui.daily_embed(RunReport(skipped=True)).description


# ── AC8：確認卡依類別分卡、封數、新卡完整發、舊卡一行提醒 ──────────────

def test_add_suggestions_依類別排序_各類別各自分卡(monkeypatch):
    monkeypatch.setattr(repo, "_max_card_no", lambda db: 7)
    db = RecSession()
    items = ([(f"p{i}@x.example", "p", "promo", "ai") for i in range(27)]
             + [(f"l{i}@x.example", "p", "login", "builtin") for i in range(3)])
    cards = repo.add_suggestions(db, items)
    assert cards == ["s8", "s9", "s10"]
    by = {}
    for r in db.added:
        by.setdefault(r.card, set()).add(r.category)
    order = [k for k, _ in config.CATEGORIES]
    assert by == {"s8": {"login"}, "s9": {"promo"}, "s10": {"promo"}}
    assert order.index("login") < order.index("promo")
    assert sum(1 for r in db.added if r.card == "s9") == 25


def test_card_counts_依寄件者加樣式數封數(monkeypatch):
    rules = [SimpleNamespace(sender="a@x.example", subject_pattern="週報 #"),
             SimpleNamespace(sender="b@x.example", subject_pattern="通知")]
    monkeypatch.setattr(repo, "_card_rows", lambda db, card: rules)
    msgs = [row("1", from_addr="a@x.example", subject_pattern="週報 #"),
            row("2", from_addr="a@x.example", subject_pattern="週報 #"),
            row("3", from_addr="a@x.example", subject_pattern="別的"),
            row("4", from_addr="a@x.example", subject_pattern="週報 #", gone_at=datetime(2026, 10, 1))]
    got = repo.card_counts(RecSession(msgs), "s3")
    assert got == {("a@x.example", "週報 #"): 2}


def test_notify_cards_卡片顯示封數_帶確認鈕(monkeypatch):
    rule = Rule(id=1, sender="a@x.example", subject_pattern="週報 #", category="promo",
                status="suggested", suggested_by="ai", card="s3")
    fake = UiRepo(pending=["s3"], unposted=["s3"])
    fake.card_rules = lambda db, card: [rule]
    fake.card_counts = lambda db, card: {("a@x.example", "週報 #"): 12}
    _wire_ui(monkeypatch, fake)
    got = []
    monkeypatch.setattr(ui, "post_sync_wait",
                        lambda ch, embeds, make_view=None, timeout=30: got.append((embeds[0], make_view)) or True)
    assert ui.notify_cards(["s3"]) == ["s3"]
    assert "12 封" in got[0][0].description

    async def go():
        assert sorted(c.custom_id for c in got[0][1]().children) == ["mailrules:confirm:s3", "mailrules:reject:s3"]
    asyncio.run(go())


def test_notify_cards_只回報並標記真的送出的卡(monkeypatch):
    fake = UiRepo(pending=["s3", "s5", "s7"], unposted=["s3", "s5", "s7"])
    _wire_ui(monkeypatch, fake, ok=lambda e: "s5" not in (e.footer.text or ""))
    assert ui.notify_cards(["s3", "s5", "s7"]) == ["s3", "s7"]
    assert fake.marked == ["s3", "s7"]


def test_notify_cards_封數查詢失敗_照發卡_每日後續不中斷(monkeypatch):
    fake = UiRepo(pending=["s3"], unposted=["s3"])

    def boom(db, card):
        raise RuntimeError("DB 斷線")
    fake.card_counts = boom
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _cards(sent) == ["s3"] and fake.marked == ["s3"]
    assert not any("失敗" in (e.title or "") for e in sent)


def test_run_daily_回報新開的卡號(monkeypatch):
    fake = FakeRepo()
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict(None, "未知", False), lambda h, v, m: [])
    rep = run.run_daily(T, db=object())
    assert rep.new_cards == ["s1"]


def test_每日後續_還沒發過的卡完整發_發過的舊卡一行提醒(monkeypatch):
    fake = UiRepo(pending=["s3", "s5", "s7", "s8"], unposted=["s8"])
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(new_cards=["s8"]), T)
    assert _cards(sent) == ["s8"] and _reminders(sent) == ["📝 還有 3 張確認卡沒處理：s3、s5、s7"]
    assert _plans(sent) == [] and fake.marked == ["s8"]


def test_每日後續_不靠_rep_new_cards_找新卡(monkeypatch):
    # run_daily 在開新卡（已 commit）之後才拋例外 → 報告丟了；DB 仍記得 s4 沒發出去過
    fake = UiRepo(pending=["s4"], unposted=["s4"])
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _cards(sent) == ["s4"] and _reminders(sent) == [] and fake.marked == ["s4"]


def test_確認卡當初沒發出去_頻道設好後完整發卡_不是一行提醒(monkeypatch):
    fake = UiRepo(pending=["s3"], unposted=["s3"])
    sent = _wire_ui(monkeypatch, fake, chan=None)            # 開卡那天頻道還沒設
    ui.after_daily(RunReport(new_cards=["s3"]), T)
    assert sent == [] and fake.marked == []
    sent = _wire_ui(monkeypatch, fake)                       # 隔天設好了
    ui.after_daily(RunReport(), T)
    assert _cards(sent) == ["s3"] and _reminders(sent) == [] and fake.marked == ["s3"]
    sent.clear()
    ui.after_daily(RunReport(), T)                           # 再隔天：發過了，只提醒
    assert _cards(sent) == [] and _reminders(sent) == ["📝 還有 1 張確認卡沒處理：s3"]


def test_確認卡送失敗_不標記_下次仍完整發(monkeypatch):
    fake = UiRepo(pending=["s3", "s5"], unposted=["s3", "s5"])
    _wire_ui(monkeypatch, fake, ok=lambda e: "s5" not in (e.footer.text or ""))
    ui.after_daily(RunReport(new_cards=["s3", "s5"]), T)
    assert fake.marked == ["s3"]
    sent = _wire_ui(monkeypatch, fake)
    ui.after_daily(RunReport(), T)
    assert _cards(sent) == ["s5"] and _reminders(sent) == ["📝 還有 1 張確認卡沒處理：s3"]


def test_post_unposted_cards_補發還沒發出的卡(monkeypatch):
    fake = UiRepo(pending=["s3", "s4"], unposted=["s4"])
    sent = _wire_ui(monkeypatch, fake)
    assert ui.post_unposted_cards() == ["s4"]
    assert _cards(sent) == ["s4"] and fake.marked == ["s4"]


def test_unposted_cards_與_mark_cards_posted():
    at = datetime(2026, 10, 1)
    rows = [SimpleNamespace(card="s3", status="suggested", posted_at=None),
            SimpleNamespace(card="s3", status="rejected", posted_at=None),
            SimpleNamespace(card="s5", status="suggested", posted_at=at),
            SimpleNamespace(card="s7", status="confirmed", posted_at=None),
            SimpleNamespace(card="s10", status="suggested", posted_at=None)]
    db = RecSession(rows)
    assert repo.unposted_cards(db) == ["s3", "s10"]
    repo.mark_cards_posted(db, ["s3"])
    assert rows[0].posted_at and rows[1].posted_at and rows[2].posted_at == at and rows[3].posted_at is None
    assert repo.unposted_cards(db) == ["s10"] and db.commits == 1


def test_舊卡提醒一行(monkeypatch):
    got = []
    monkeypatch.setattr(ui, "_post", lambda embeds, make_view=None: got.append(embeds))
    monkeypatch.setattr(ui.config, "mail_channel_id", lambda: 123)
    ui.notify_card_reminder(["s3", "s5", "s7"])
    assert len(got) == 1 and "還有 3 張確認卡沒處理：s3、s5、s7" in got[0][0].description


# ── AC9：小修 ─────────────────────────────────────────────────────

def test_手動指定不提供_keep_inbox():
    async def go():
        vals = [o.value for o in ui.AssignSelect(7, "x").item.options]
        assert "keep_inbox" not in vals and "promo" in vals
    asyncio.run(go())


def test_計畫卡未知寫成樣式():
    e = ui.history_embed({"counts": {}, "samples": {}, "pending_cards": 0, "unknown": 4})
    assert "未知 4 個樣式" in e.description


def test_計畫範例主旨去重_一封信多個動作只算一個(monkeypatch):
    fake = FakeRepo()
    fake.max_card = lambda db: None
    fake.store = {"m1": H("m1", subject="A"), "m2": H("m2", subject="A"), "m3": H("m3", subject="B"),
                  "m4": H("m4", subject="C")}
    wire(monkeypatch, fake, [], lambda h: Verdict("promo", "規則", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "label", "整理/x"), Action(h.gm_msgid, h.uid, "trash")])
    plan = run.history_plan(T, db=object())
    assert plan["samples"]["promo"] == ["A", "B", "C"]
    assert plan["counts"] == {("promo", "label"): 4, ("promo", "trash"): 4}
    assert plan["upto_card"] is None
