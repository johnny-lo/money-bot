from types import SimpleNamespace

from mailrules import repo
from mailrules.types import Action


class FakeQuery:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, rows=()):
        self.rows, self.added, self.commits = list(rows), [], 0
    def query(self, *a, **k): return FakeQuery(self.rows)
    def add(self, o): self.added.append(o)
    def flush(self): pass
    def commit(self): self.commits += 1
    def rollback(self): pass


def msg(gid, **kw):
    base = dict(gm_msgid=gid, uid=1, in_inbox=True, labels_applied=[], trashed_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_record_actions_冪等欄位():
    rows = [msg("a"), msg("b"), msg("c")]
    db = FakeSession(rows)
    repo.record_actions(db, [Action("a", 1, "label", "整理/收據"), Action("a", 1, "archive"),
                             Action("b", 1, "trash"), Action("c", 1, "label", "整理/收據")])
    assert rows[0].labels_applied == ["整理/收據"] and rows[0].in_inbox is False
    assert rows[1].trashed_at is not None
    repo.record_actions(db, [Action("c", 1, "label", "整理/收據")])
    assert rows[2].labels_applied == ["整理/收據"]                     # 不重複加
    assert db.commits == 2


def test_add_suggestions_每25筆一張卡_卡號只增不減(monkeypatch):
    monkeypatch.setattr(repo, "_max_card_no", lambda db: 7)
    db = FakeSession()
    cards = repo.add_suggestions(db, [(f"a{i}@x.example", "p", "promo", "ai") for i in range(30)])
    assert cards == ["s8", "s9"]
    assert [r.card for r in db.added].count("s8") == 25 and db.commits == 1


def test_confirm_card_只動該卡的_suggested(monkeypatch):
    rows = [SimpleNamespace(id=1, card="s3", status="suggested", confirmed_at=None),
            SimpleNamespace(id=2, card="s3", status="suggested", confirmed_at=None),
            SimpleNamespace(id=3, card="s3", status="confirmed", confirmed_at="x")]
    monkeypatch.setattr(repo, "_card_rows", lambda db, card: rows)
    db = FakeSession()
    assert repo.confirm_card(db, "s3", [2]) == (1, 1)
    assert [r.status for r in rows] == ["confirmed", "rejected", "confirmed"]
    assert db.commits == 1
