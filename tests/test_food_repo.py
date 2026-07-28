"""upsert_place 的寫入契約（用 FakeSession，不連 DB；照 test_food_photos.py 的姿態）。

這裡測的是最會靜默爛資料的兩件事：
① 非空欄位不可被空值覆寫；② 分類不可被重新匯入打回規則值。
"""
import pytest

from food import repo


# ── normalize_region：純函式 ──────────────────────────────────

def test_台灣收斂成全名與合法行政區():
    place = {"country": "台灣", "city": "桃園", "district": "興南里"}
    assert repo.normalize_region(place) == ("台灣", "桃園市", None)   # 里被拒收


def test_台灣行政區留得住():
    place = {"country": "台灣", "city": "新竹縣", "district": "竹北市"}
    assert repo.normalize_region(place) == ("台灣", "新竹縣", "竹北市")


def test_國外原樣放行():
    """國外是開放詞彙，硬套台灣的表只會把「新宿區」洗掉。"""
    place = {"country": "日本", "city": "東京", "district": "新宿區"}
    assert repo.normalize_region(place) == ("日本", "東京", "新宿區")


# ── upsert_place：用假的 session 驗寫入契約 ────────────────────

class FakeRec:
    # 類別屬性：repo 用 FoodPlace.place_id 組 filter 條件，那是存取類別而非實例
    place_id = None
    id = None

    def __init__(self, **kw):
        for f in ("id", "name", "address", "lat", "lng", "place_id", "country", "city",
                  "district", "cuisine_type", "cuisine_major", "cuisine_minor",
                  "recommended_items", "caution_summary", "status", "my_rating",
                  "my_note", "source_url", "created_at"):
            setattr(self, f, None)
        self.id = 1
        self.status = "想去"
        for k, v in kw.items():
            setattr(self, k, v)


class FakeQuery:
    def __init__(self, rec):
        self._rec = rec

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._rec


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []

    def query(self, *a):
        return FakeQuery(self.existing)

    def add(self, rec):
        self.added.append(rec)
        self.existing = rec

    def commit(self):
        pass

    def refresh(self, rec):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    holder = {}

    def factory():
        return holder["session"]

    monkeypatch.setattr(repo, "SessionLocal", factory)
    monkeypatch.setattr(repo, "FoodPlace", FakeRec)
    return holder


def _place(**kw):
    base = {"place_id": "p1", "name": "測試店", "address": "320台灣桃園市中壢區中正路1號",
            "lat": 24.9, "lng": 121.2, "country": "台灣", "city": "桃園市",
            "district": "中壢區"}
    base.update(kw)
    return base


def test_新店會分類(fake_db):
    fake_db["session"] = FakeSession(existing=None)
    out, created = repo.upsert_place(_place(name="極清拉麵"))
    assert created is True
    assert out["cuisine_major"] == "日式"      # 沒給 cuisine_type 也能從店名判
    assert out["city"] == "桃園市"


def test_退化回應不會把好資料抹成空(fake_db):
    """Places 偶爾回傳缺 addressComponents 的結果 → 舊版會直接把 city/district 寫成 None。"""
    old = FakeRec(place_id="p1", name="舊名", city="桃園市", district="中壢區",
                  address="舊地址", lat=24.9, lng=121.2)
    fake_db["session"] = FakeSession(existing=old)
    out, created = repo.upsert_place(
        {"place_id": "p1", "name": "新名", "city": None, "district": None,
         "country": None, "address": None, "lat": None, "lng": None}
    )
    assert created is False
    assert out["name"] == "新名"          # 有值的照常更新
    assert out["city"] == "桃園市"        # 空值不覆寫
    assert out["district"] == "中壢區"
    assert out["address"] == "舊地址"


def test_重新匯入不會打回手動分類(fake_db):
    """既有店沒帶新的 cuisine_type → 不重算，手動修正過的大類留著。"""
    old = FakeRec(place_id="p1", name="極清拉麵", cuisine_type=None,
                  cuisine_major="韓式", cuisine_minor="手動改過")
    fake_db["session"] = FakeSession(existing=old)
    out, _ = repo.upsert_place(_place(name="極清拉麵"))
    assert out["cuisine_major"] == "韓式"
    assert out["cuisine_minor"] == "手動改過"


def test_帶新的原始文字才重算分類(fake_db):
    old = FakeRec(place_id="p1", name="某店", cuisine_major="韓式")
    fake_db["session"] = FakeSession(existing=old)
    out, _ = repo.upsert_place(_place(), cuisine_type="日式燒肉")
    assert out["cuisine_major"] == "日式"
    assert out["cuisine_minor"] == "燒肉"
    assert out["cuisine_type"] == "日式燒肉"   # 原始文字保留供稽核


def test_判不出大類時不清掉既有值(fake_db):
    old = FakeRec(place_id="p1", name="某店", cuisine_major="台式")
    fake_db["session"] = FakeSession(existing=old)
    out, _ = repo.upsert_place(_place(), cuisine_type="小館")   # 垃圾值，判不出
    assert out["cuisine_major"] == "台式"
