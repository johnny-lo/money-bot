import os

import pytest

import food.photos as photos


class FakeRec:
    def __init__(self, id=None, food_place_id=None, path=None, source="app"):
        self.id = id
        self.food_place_id = food_place_id
        self.path = path
        self.source = source
        self.created_at = None


class FakeQuery:
    def __init__(self, store):
        self._store = store

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._store.get("hit")


class FakeSession:
    """模擬 photos 需要的最小 session 介面。

    mode:
      - 'clean'        : commit 成功
      - 'commit_fail'  : commit 丟 RuntimeError（模擬 DB 掛掉/約束衝突）
    """
    def __init__(self, mode="clean", hit=None):
        self.mode = mode
        self._store = {"hit": hit}
        self.added = []
        self.deleted = []
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def query(self, *a, **k):
        return FakeQuery(self._store)

    def add(self, rec):
        self.added.append(rec)

    def delete(self, rec):
        self.deleted.append(rec)

    def commit(self):
        if self.mode == "commit_fail":
            raise RuntimeError("DB down")
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def refresh(self, rec):
        if rec.id is None:
            rec.id = 1

    def close(self):
        self.closed = True


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "MEDIA_ROOT", str(tmp_path))
    return tmp_path


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(photos, "SessionLocal", lambda: session)
    return session


def test_add_photo_writes_file_and_db(media_root, monkeypatch):
    s = _patch_session(monkeypatch, FakeSession("clean"))
    out = photos.add_photo(7, b"fakejpg", "png", source="bot")
    assert out["url"].startswith("/media/food/7/")
    assert out["url"].endswith(".png")
    assert out["source"] == "bot"
    rel = out["url"].removeprefix("/media/")
    assert (media_root / rel).read_bytes() == b"fakejpg"
    assert s.committed == 1 and s.closed


def test_add_photo_bad_ext_falls_back_jpg(media_root, monkeypatch):
    _patch_session(monkeypatch, FakeSession("clean"))
    out = photos.add_photo(7, b"x", "exe")
    assert out["url"].endswith(".jpg")


def test_add_photo_db_fail_removes_file(media_root, monkeypatch):
    s = _patch_session(monkeypatch, FakeSession("commit_fail"))
    with pytest.raises(RuntimeError):
        photos.add_photo(7, b"x", "jpg")
    # DB 沒寫成 → 檔案不能留下（一致性）
    leftover = list((media_root / "food" / "7").glob("*")) if (media_root / "food" / "7").exists() else []
    assert leftover == []
    assert s.rolled_back == 1 and s.closed


def test_delete_photo_missing_file_still_deletes_row(media_root, monkeypatch):
    rec = FakeRec(id=3, food_place_id=7, path="food/7/ghost.jpg")
    s = _patch_session(monkeypatch, FakeSession("clean", hit=rec))
    assert photos.delete_photo(3) is True
    assert s.deleted == [rec] and s.committed == 1


def test_delete_photo_not_found(media_root, monkeypatch):
    s = _patch_session(monkeypatch, FakeSession("clean", hit=None))
    assert photos.delete_photo(99) is False
    assert s.deleted == [] and s.committed == 0


def test_delete_files_for_place_removes_dir(media_root):
    d = media_root / "food" / "5"
    d.mkdir(parents=True)
    (d / "a.jpg").write_bytes(b"x")
    photos.delete_files_for_place(5)
    assert not d.exists()


def test_delete_files_for_place_no_dir_is_noop(media_root):
    photos.delete_files_for_place(404)  # 不存在不應丟例外
