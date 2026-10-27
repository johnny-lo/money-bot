import json
from datetime import datetime
from types import SimpleNamespace

from lineinbox import repo
from lineinbox.types import NEEDS_CODEX, OK, ERROR, InboxMessage

T = datetime(2026, 9, 5, 19, 43)


def msg(mid="900000000000000001", kind="spend"):
    return InboxMessage(message_id=mid, source="ctbc", sent_at=T, alt_text="消費通知", content_type=22,
                        texts=["刷卡通知", "NT$1,280"], kind=kind)


class FakeQuery:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def limit(self, n): return FakeQuery(self.rows[:n])
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def count(self): return len(self.rows)


class FakeSession:
    def __init__(self, rows=()):
        self.rows, self.added, self.commits = list(rows), [], 0
    def query(self, *a, **k): return FakeQuery(self.rows)
    def add(self, o): self.added.append(o)
    def commit(self): self.commits += 1
    def get(self, model, pk): return self.rows[0] if self.rows else None


def test_save_message_新訊息_寫入():
    db = FakeSession()
    assert repo.save_message(db, msg(), NEEDS_CODEX) is True
    row = db.added[0]
    assert (row.message_id, row.source, row.kind, row.status, row.sent_at) == \
        ("900000000000000001", "ctbc", "spend", "needs_codex", T)
    assert json.loads(row.texts) == ["刷卡通知", "NT$1,280"]
    assert db.commits == 1


def test_save_message_已存在_不覆蓋():
    db = FakeSession(rows=[SimpleNamespace(message_id="900000000000000001", status="parsed")])
    assert repo.save_message(db, msg(), NEEDS_CODEX) is False
    assert db.added == [] and db.rows[0].status == "parsed"


def test_pending_codex_還原成InboxMessage():
    row = SimpleNamespace(message_id="9", source="ctbc", sent_at=T, alt_text=None, content_type=22,
                          texts=json.dumps(["刷卡通知"]), kind="spend", status=NEEDS_CODEX)
    got = repo.pending_codex(FakeSession(rows=[row]), limit=5)
    assert got == [InboxMessage("9", "ctbc", T, None, 22, ["刷卡通知"], "spend")]


def test_set_state_沒有列就建_OK才更新心跳():
    db = FakeSession()
    repo.set_state(db, OK, now=T)
    row = db.added[0]
    assert (row.id, row.state, row.heartbeat_at, row.alerted) == (1, "ok", T, None)


def test_set_state_錯誤不動心跳_OK清掉已告警():
    row = SimpleNamespace(id=1, state="ok", heartbeat_at=T, last_error=None, alerted="stale")
    db = FakeSession(rows=[row])
    later = datetime(2026, 9, 5, 21, 0)
    repo.set_state(db, ERROR, "ConnectionError", now=later)
    assert (row.state, row.heartbeat_at, row.last_error, row.alerted) == ("error", T, "ConnectionError", "stale")
    repo.set_state(db, OK, now=later)
    assert (row.state, row.heartbeat_at, row.last_error, row.alerted) == ("ok", later, None, None)


def test_listener_state_沒有列回None():
    assert repo.listener_state(FakeSession()) is None
