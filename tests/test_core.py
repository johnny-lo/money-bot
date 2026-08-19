"""core.py 的保護網：指令路由、記帳文字解析、CRUD data 函式、圖片記帳解析。

全部 FakeSession + monkeypatch AI 呼叫，不碰真 DB / 不打 API。
"""
import pytest

import core


class FakeSession:
    """最小 session：add/flush 給 id、query.filter.first 回預設 hit。"""

    def __init__(self, hit=None):
        self.hit = hit
        self.added = []
        self.deleted = []
        self.committed = 0
        self.rolled_back = 0
        self._next_id = 0

    def query(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        return self.hit

    def add(self, rec):
        self.added.append(rec)

    def flush(self):
        for r in self.added:
            if getattr(r, "id", None) is None:
                self._next_id += 1
                r.id = self._next_id

    def refresh(self, rec):
        if getattr(rec, "id", None) is None:
            self._next_id += 1
            rec.id = self._next_id

    def delete(self, rec):
        self.deleted.append(rec)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    s = FakeSession()
    monkeypatch.setattr(core, "SessionLocal", lambda: s)
    return s


@pytest.fixture(autouse=True)
def no_persona(monkeypatch):
    monkeypatch.setattr(core, "generate_persona_comment", lambda *_, **__: "")


# ── process_text_message 路由分流 ───────────────────────────────

def test_route_help():
    assert core.process_text_message("說明") == [core.HELP_TEXT]
    assert core.process_text_message("help") == [core.HELP_TEXT]


@pytest.mark.parametrize("msg,handler,expected_args", [
    ("分類", "handle_categorize", ()),
    ("固定清單", "handle_list_recurring", ()),
    ("查詢", "handle_query_monthly", ()),
    ("最近", "handle_query_recent", ()),
    ("取消固定 3", "handle_delete_recurring", (3,)),
    ("刪除收入 5", "handle_delete_income", (5,)),
    ("刪除 5", "handle_delete_expense", (5,)),
    ("抓發票", "handle_fetch_invoices", (1,)),
    ("抓發票 7", "handle_fetch_invoices", (7,)),
    ("修改 5 滷肉飯 100", "handle_update_expense", (5, "滷肉飯", 100)),
    ("修改收入 5 獎金 1000", "handle_update_income", (5, "獎金", 1000)),
    ("固定 支出 房租 15000 1", "handle_add_recurring", ("支出", "房租", 15000, 1)),
    # 尾巴的「共同」是可選旗標，不能被吃進品名裡
    ("固定 支出 房租 15000 1 共同", "handle_add_recurring", ("支出", "房租", 15000, 1)),
])
def test_route_dispatch(monkeypatch, msg, handler, expected_args):
    calls = []
    monkeypatch.setattr(core, handler, lambda *a, **kw: calls.append(a) or "OK")
    assert core.process_text_message(msg) == ["OK"]
    assert calls == [expected_args]


def test_route_report_needs_context(monkeypatch):
    monkeypatch.setattr(core, "handle_report", lambda uid, base: f"{uid}@{base}")
    assert core.process_text_message("報表", user_id="u1", base_url="https://x") == ["u1@https://x"]
    # 沒帶 user_id/base_url（理論上不會發生）→ 落到一般記帳 → None
    monkeypatch.setattr(core, "handle_record_text", lambda m, **__: None)
    assert core.process_text_message("報表") is None


def test_route_fallback_to_record(monkeypatch):
    monkeypatch.setattr(core, "handle_record_text", lambda m, **__: ["記了"])
    assert core.process_text_message("午餐 150") == ["記了"]


# ── handle_record_text 記帳解析 ────────────────────────────────

def test_record_single_expense(fake_db):
    out = core.handle_record_text("午餐 150")
    assert out is not None and "午餐：150 元" in out[0]
    assert fake_db.committed == 1
    assert len(fake_db.added) == 1
    assert fake_db.added[0].price == 150


def test_record_multiline_mixed(fake_db):
    out = core.handle_record_text("午餐 150\n\n收入 薪水 50000\n這行不是記帳\n飲料 60")
    text = out[0]
    assert "午餐：150 元" in text
    assert "薪水：50000 元" in text and "💰 收入" in text
    assert "飲料：60 元" in text
    assert "這行不是記帳" not in text
    assert len(fake_db.added) == 3   # 2 支出 + 1 收入


def test_record_skips_command_like_lines(fake_db):
    # 「刪除 99」長得像 `品名 金額`，但必須被指令前綴防呆擋掉，不能記成支出
    assert core.handle_record_text("刪除 99") is None
    assert core.handle_record_text("修改 3 麵 100") is None
    assert fake_db.added == []


def test_record_no_match_returns_none(fake_db):
    assert core.handle_record_text("今天天氣真好") is None
    assert fake_db.committed == 0


def test_record_appends_persona_when_present(fake_db, monkeypatch):
    monkeypatch.setattr(core, "generate_persona_comment", lambda *_, **__: "🐉 吼！")
    out = core.handle_record_text("午餐 150")
    assert out[1] == "🐉 吼！"


# ── CRUD data 函式（Discord/PWA 共用層）─────────────────────────

def test_record_expense_data_success(fake_db):
    out = core.record_expense_data("便當", 100)
    assert out["success"] is True and out["id"] == 1 and out["amount"] == 100


def test_update_expense_data_not_found(fake_db):
    out = core.update_expense_data(99, "x", 1)
    assert out["success"] is False and "找不到" in out["error"]


def test_update_expense_data_success(monkeypatch):
    from models import Transaction
    rec = Transaction(item="舊", price=50)
    rec.id = 7
    s = FakeSession(hit=rec)
    monkeypatch.setattr(core, "SessionLocal", lambda: s)
    out = core.update_expense_data(7, "新", 80)
    assert out["success"] is True
    assert out["old"] == {"item": "舊", "amount": 50}
    assert out["new"] == {"item": "新", "amount": 80}
    assert rec.item == "新" and rec.price == 80


def test_delete_income_data_success(monkeypatch):
    from models import Income
    rec = Income(item="獎金", amount=1000)
    rec.id = 3
    s = FakeSession(hit=rec)
    monkeypatch.setattr(core, "SessionLocal", lambda: s)
    out = core.delete_income_data(3)
    assert out["success"] is True and out["item"] == "獎金"
    assert s.deleted == [rec]


def test_add_recurring_data_day_out_of_range(fake_db):
    assert core.add_recurring_data("支出", "房租", 15000, 31)["success"] is False
    assert core.add_recurring_data("支出", "房租", 15000, 0)["success"] is False
    assert fake_db.added == []


# ── handle_image_data 圖片記帳（mock gemini）────────────────────

def _set_gemini(monkeypatch, payload: str):
    monkeypatch.setattr(core, "gemini_image", lambda prompt, b: payload)


def test_image_data_with_discount(fake_db, monkeypatch):
    _set_gemini(monkeypatch, '```json\n[{"item":"雞肉","price":150},'
                             '{"item":"促銷折抵","price":-20},{"item":"忽略","price":0}]\n```')
    out = core.handle_image_data(b"img")
    assert out["success"] is True
    assert out["total_expense"] == 150
    assert out["total_discount"] == 20
    assert out["actual"] == 130
    # 折扣記成「收入」（DB 無負數金額的設計）
    assert out["discounts"][0]["item"] == "促銷折抵"
    assert len(fake_db.added) == 2   # price=0 跳過


def test_image_data_bad_json(fake_db, monkeypatch):
    _set_gemini(monkeypatch, "看不懂的回答")
    out = core.handle_image_data(b"img")
    assert out["success"] is False and "無法解析" in out["error"]


def test_image_data_empty_list(fake_db, monkeypatch):
    _set_gemini(monkeypatch, "[]")
    out = core.handle_image_data(b"img")
    assert out["success"] is False


def test_固定支出的共同旗標有傳到處理函式(monkeypatch):
    """「共同」只被 regex 吃掉、沒傳下去的話，這個功能等於不存在（設得了但沒作用）。"""
    seen = {}
    monkeypatch.setattr(core, "handle_add_recurring",
                        lambda *a, **kw: seen.update(kw) or "OK")
    core.process_text_message("固定 支出 房租 12000 5 共同")
    assert seen.get("shared") is True
    seen.clear()
    core.process_text_message("固定 支出 我的手機分期 5800 10")
    assert seen.get("shared") is False
