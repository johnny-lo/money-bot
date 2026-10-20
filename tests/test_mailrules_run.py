from dataclasses import replace
from datetime import date

from mailrules import run
from mailrules.types import Action, MailHeader, MessageState, RunReport, Verdict

T = date(2026, 10, 12)


def H(gid, addr="a@shop.example", subject="s", d=T):
    return MailHeader(gm_msgid=gid, uid=int(gid[1:]), from_addr=addr, from_name="", subject=subject,
                      sent_date=d, labels=(), unsub=True, in_inbox=True)


class FakeRepo:
    def __init__(self, history_done=False):
        self.state = None if not history_done else (1, 0, "done")
        self.recorded, self.suggested, self.valued = [], [], {}
        self.store = {}
    def get_state(self, db): return self.state
    def set_state(self, db, uidv, last): self.state = (uidv, last, self.state[2] if self.state else None)
    def upsert_headers(self, db, hs, owner):
        for h in hs: self.store[h.gm_msgid] = h
        return len(hs)
    def headers(self, db): return list(self.store.values())
    def states(self, db): return {g: MessageState(in_inbox=True) for g in self.store}
    def add_valued(self, db, d): self.valued.update(d)
    def valued_set(self, db): return set(self.valued)
    def ensure_promo_wildcards(self, db, valued): return 0
    def pending_valued_count(self, db): return 0
    def confirmed_rules(self, db): return []
    def known_keys(self, db): return set()
    def save_verdicts(self, db, v): self.verdicts = v
    def add_suggestions(self, db, items): self.suggested += items; return ["s1"] if items else []
    def record_actions(self, db, done): self.recorded += done
    def pending_cards(self, db): return []
    def mark_history_done(self, db): self.state = (self.state[0], self.state[1], "done")


def wire(monkeypatch, fake, headers, verdict, actions):
    monkeypatch.setattr(run, "repo", fake)
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda since: (1, headers))
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: (acts, [], []))
    monkeypatch.setattr(run, "subject_pattern", lambda s, o: s)
    monkeypatch.setattr(run.C, "learn_valued_domains", lambda hs, s, c: {})
    monkeypatch.setattr(run.C, "classify", lambda h, p, r, v, s: verdict(h))
    monkeypatch.setattr(run.C, "builtin_suggest", lambda h, p, c: None)
    monkeypatch.setattr(run, "plan_actions", lambda h, v, st, today, mode: actions(h, v, mode))
    monkeypatch.setattr(run.suggest, "suggest", lambda groups: {(g["sender"], g["pattern"]): "promo" for g in groups})


def test_歷史未完成前_每日只分類建議_不寫入(monkeypatch):
    fake = FakeRepo(history_done=False)
    called = []
    wire(monkeypatch, fake, [H("m1"), H("m2", addr="b@x.example")],
         lambda h: Verdict(None, "未知", False), lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: called.append(acts) or (acts, [], []))
    rep = run.run_daily(T, db=object())
    assert rep.applied is False and called == [] and fake.recorded == []
    assert len(fake.suggested) == 2


def test_歷史完成後_每日照規劃執行並記錄(monkeypatch):
    fake = FakeRepo(history_done=True)
    wire(monkeypatch, fake, [H("m1"), H("m2")], lambda h: Verdict("login", "規則 #1", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])
    rep = run.run_daily(T, db=object())
    assert rep.applied and rep.counts == {("login", "trash"): 2} and len(fake.recorded) == 2


def test_suggest_失敗_只留內建建議_不擋流程(monkeypatch):
    fake = FakeRepo()
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict(None, "未知", False), lambda h, v, m: [])
    monkeypatch.setattr(run.suggest, "suggest", lambda groups: (_ for _ in ()).throw(RuntimeError("codex")))
    run.run_daily(T, db=object())
    assert fake.suggested == []


def test_還有確認卡沒處理_拒絕執行歷史(monkeypatch):
    fake = FakeRepo()
    fake.pending_cards = lambda db: ["s1"]
    monkeypatch.setattr(run, "repo", fake)
    try:
        run.execute_history(T, db=object())
    except RuntimeError as e:
        assert "確認卡" in str(e)
    else:
        raise AssertionError


# ── 歷史全量同步、完成後拒絕重跑、UIDVALIDITY 中止不標完成 ───────────────

class LossyRepo(FakeRepo):
    """模擬真 DB：不存 List-Unsubscribe / 顯示名稱，headers() 讀回來 unsub 一律 False。"""
    def headers(self, db): return [replace(h, unsub=False) for h in self.store.values()]


def wire_since(monkeypatch, fake, all_headers, seen_unsub, since_log):
    def read_headers(since):
        since_log.append(since)
        return 1, [h for h in all_headers if since is None or h.uid > since]

    def verdict(h):
        seen_unsub[h.gm_msgid] = h.unsub
        return Verdict(None, "未知", False)
    wire(monkeypatch, fake, [], verdict, lambda h, v, m: [])
    monkeypatch.setattr(run.gmail_rw, "read_headers", read_headers)


def test_prepare_history_全量同步_舊信的_unsub_不會丟(monkeypatch):
    fake = LossyRepo()
    fake.state = (1, 50, None)                        # 每日排程已跑過：高水位 50，舊信 uid 都在它下面
    seen, since = {}, []
    wire_since(monkeypatch, fake, [H("m1"), H("m2"), H("m3")], seen, since)
    run.prepare_history(T, db=object())
    assert since == [None]                             # 不是 [50]
    assert seen == {"m1": True, "m2": True, "m3": True}
    assert fake.state[1] == 3


def test_execute_history_已完成_拒絕重跑(monkeypatch):
    fake = FakeRepo(history_done=True)
    called, since = [], []
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict("promo", "規則", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])
    monkeypatch.setattr(run.gmail_rw, "apply", lambda acts: called.append(acts) or (acts, [], []))
    monkeypatch.setattr(run.gmail_rw, "read_headers", lambda s: since.append(s) or (1, []))
    try:
        run.execute_history(T, db=object())
    except RuntimeError as e:
        assert "已完成" in str(e)
    else:
        raise AssertionError
    assert called == [] and since == []


def test_execute_history_開頭先全量同步(monkeypatch):
    fake = LossyRepo()
    fake.state = (1, 50, None)
    seen, since = {}, []
    wire_since(monkeypatch, fake, [H("m1"), H("m2")], seen, since)
    run.execute_history(T, db=object())
    assert since == [None] and seen == {"m1": True, "m2": True}
    assert fake.state[2] == "done"


def test_execute_history_apply_中止_不標記完成(monkeypatch):
    fake = LossyRepo()
    fake.state = (1, 0, None)
    wire(monkeypatch, fake, [H("m1")], lambda h: Verdict("promo", "規則", False),
         lambda h, v, m: [Action(h.gm_msgid, h.uid, "trash")])

    def boom(acts):
        raise run.gmail_rw.UidValidityChanged("變了")
    monkeypatch.setattr(run.gmail_rw, "apply", boom)
    try:
        run.execute_history(T, db=object())
    except run.gmail_rw.UidValidityChanged:
        pass
    else:
        raise AssertionError
    assert fake.state[2] is None and fake.recorded == []
