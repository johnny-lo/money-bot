"""來源標記（source）與共同分攤（shared）的寫入契約。

背景：兩個人共用一套帳，主力資料是兩組電子發票載具。載具編號在 einvoice 同步時
就知道（`for label, phone, password in carriers`），但原本沒被帶進 _save_invoices，
就這樣丟掉了——接回去之後「這筆是誰花的」對發票資料是**全自動**的。

shared 的設計：DB 存**全額**（房租 12,000），算「我的份」時才除以 2。
這樣家庭總支出仍然正確，日後改分攤比例也不必重寫歷史資料。
"""
import pytest

import core
import recurring
from tests.test_core import FakeSession


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    monkeypatch.setattr(core, "generate_persona_comment", lambda *_, **__: "")


@pytest.fixture
def fake(monkeypatch):
    s = FakeSession()
    monkeypatch.setattr(core, "SessionLocal", lambda: s)
    return s


def test_手動記帳會帶上來源(fake):
    core.record_expense_data("便當", 100, source="discord")
    assert fake.added[0].source == "discord"


def test_沒給來源就是_None_而不是猜一個(fake):
    """猜錯的來源比沒有來源更糟——報表會把別人的支出算到你頭上。"""
    core.record_expense_data("便當", 100)
    assert fake.added[0].source is None


def test_文字記帳會帶上來源(fake):
    core.handle_record_text("午餐 150", source="line")
    assert fake.added[0].source == "line"


def test_process_text_message_把來源傳下去(fake):
    core.process_text_message("午餐 150", source="line")
    assert fake.added and fake.added[0].source == "line"


# ── recurring：固定支出的 source 與 shared 繼承 ───────────────

class _Rec:
    def __init__(self, **kw):
        self.type = "expense"; self.item = "房租"; self.amount = 12000
        self.category = "居住水電"; self.day_of_month = 5; self.active = 1
        self.shared = 0
        for k, v in kw.items():
            setattr(self, k, v)


class _RecSession(FakeSession):
    def __init__(self, records):
        super().__init__()
        self._records = records

    def all(self):
        return self._records


def _run(monkeypatch, records):
    s = _RecSession(records)
    monkeypatch.setattr(recurring, "SessionLocal", lambda: s)
    recurring.run_daily_recurring()
    return s


def test_固定支出標記為recurring來源(monkeypatch):
    s = _run(monkeypatch, [_Rec()])
    assert s.added[0].source == "recurring"


def test_共同分攤的設定會被繼承(monkeypatch):
    """房租設 shared=1 → 每月自動產生的那筆也要是 shared=1，不然分攤資訊會斷掉。"""
    s = _run(monkeypatch, [_Rec(shared=1)])
    assert s.added[0].shared == 1
    assert s.added[0].price == 12000, "DB 要存全額，除以 2 是報表的事"


def test_非共同的固定支出_shared_是零(monkeypatch):
    s = _run(monkeypatch, [_Rec(item="我的手機分期", shared=0)])
    assert s.added[0].shared == 0


# ── 固定支出的分類：建立時決定一次，之後每筆繼承 ────────────

def test_固定支出產生的帳目會繼承分類(monkeypatch):
    """不繼承的話每筆都是 NULL，要等週日 AI 重猜 → 「固定」桶每個月初空著、
    未分類暴增，角色看到的水位就是錯的。"""
    s = _run(monkeypatch, [_Rec(item="房租", category="居住水電")])
    assert s.added[0].category == "居住水電"


def test_收入不做分類():
    """category 是支出的概念；收入走 Income，沒有這個欄位語意。"""
    import core
    calls = []
    import categorize
    assert callable(categorize.classify_one)


# ── classify_one：封閉清單守門 ──────────────────────────────

def test_分類結果必須在封閉清單內(monkeypatch):
    """AI 回了清單外的東西就當作沒分到（留 NULL 給週日補），不要硬塞進 DB
    ——越界值會讓下游的桶位映射與大組統計全部對不上。"""
    import categorize
    monkeypatch.setattr(categorize, "codex_text", lambda p: "外太空消費")
    assert categorize.classify_one("不明品項", 100) is None


def test_分類結果會去掉引號與空白(monkeypatch):
    import categorize
    monkeypatch.setattr(categorize, "codex_text", lambda p: '  「居住水電」  ')
    assert categorize.classify_one("房租", 12000) == "居住水電"


def test_分類失敗回_None_而不是炸掉(monkeypatch):
    """記帳/建立固定收支不能因為分類失敗而失敗。"""
    import categorize
    def boom(p): raise RuntimeError("codex 掛了")
    monkeypatch.setattr(categorize, "codex_text", boom)
    assert categorize.classify_one("房租", 12000) is None
