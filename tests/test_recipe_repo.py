import pytest
from sqlalchemy.exc import IntegrityError

import recipe.repo as repo


class FakeRec:
    def __init__(self, id, name, url, platform):
        self.id = id
        self.name = name
        self.url = url
        self.platform = platform
        self.discord_message_id = None
        self.created_at = None


class FakeQuery:
    def __init__(self, store):
        self._store = store
    def filter(self, *a, **k):
        return self
    def first(self):
        return self._store.get("hit")


class FakeSession:
    """模擬 add_recipe 需要的最小 session 介面。

    behavior:
      - 'clean'   ：SELECT 永遠落空、commit 成功 → 正常 INSERT 新建
      - 'race'    ：第一次 SELECT 落空（hit=None），commit 丟 IntegrityError，
                    rollback 後把 hit 換成既有列 → 走 IntegrityError 分支回 created=False
    """
    def __init__(self, mode):
        self.mode = mode
        self._hit_store = {"hit": None}
        self.added = []
        self.committed = 0
        self.rolled_back = 0
        self._existing = FakeRec(7, "既有菜", "https://x/dup", "youtube")

    def query(self, *a, **k):
        return FakeQuery(self._hit_store)
    def add(self, rec):
        self.added.append(rec)
    def commit(self):
        if self.mode == "race" and self.committed == 0:
            self.committed += 1
            raise IntegrityError("INSERT", {}, Exception("UNIQUE"))
        self.committed += 1
    def rollback(self):
        self.rolled_back += 1
        self._hit_store["hit"] = self._existing
    def refresh(self, rec):
        if rec.id is None:
            rec.id = 1
    def close(self):
        pass


def test_add_recipe_creates_when_clean(monkeypatch):
    sess = FakeSession("clean")
    monkeypatch.setattr(repo, "SessionLocal", lambda: sess)
    rec, created = repo.add_recipe("番茄炒蛋", "https://x/new", "youtube")
    assert created is True
    assert rec["name"] == "番茄炒蛋"
    assert rec["url"] == "https://x/new"
    assert len(sess.added) == 1


def test_add_recipe_integrity_error_returns_existing(monkeypatch):
    sess = FakeSession("race")
    monkeypatch.setattr(repo, "SessionLocal", lambda: sess)
    rec, created = repo.add_recipe("重複菜", "https://x/dup", "youtube")
    assert created is False
    assert rec["id"] == 7
    assert rec["name"] == "既有菜"
    assert sess.rolled_back == 1


def test_add_recipe_returns_existing_when_already_present(monkeypatch):
    sess = FakeSession("clean")
    sess._hit_store["hit"] = FakeRec(3, "舊菜", "https://x/old", "tiktok")
    monkeypatch.setattr(repo, "SessionLocal", lambda: sess)
    rec, created = repo.add_recipe("新名字會被忽略", "https://x/old", "tiktok")
    assert created is False
    assert rec["id"] == 3
    assert rec["name"] == "舊菜"
    assert sess.added == []


def test_pick_random_empty(monkeypatch):
    monkeypatch.setattr(repo, "list_recipes", lambda: [])
    assert repo.pick_random() is None


def test_pick_random_single(monkeypatch):
    monkeypatch.setattr(repo, "list_recipes",
                        lambda: [{"id": 1, "name": "唯一菜", "url": "u"}])
    one = repo.pick_random()
    assert one["name"] == "唯一菜"


def test_pick_random_from_many(monkeypatch):
    rows = [{"id": i, "name": f"菜{i}", "url": f"u{i}"} for i in range(5)]
    monkeypatch.setattr(repo, "list_recipes", lambda: rows)
    picked = repo.pick_random()
    assert picked in rows
