"""發票消費要記得「賣方是誰」（Transaction.seller 的寫入契約）。

背景：`_save_invoices()` 一直都拿得到 `inv["seller"]`——`format_item()` 用它把純代號
品名補成「賣方-代號」，保底那筆更直接拿它當品名——但**從來沒寫進 Transaction**。
結果 DB 裡的發票消費只剩品名與金額，「這筆錢花在哪家店」在爬蟲當下就蒸發了，
`transactions` 也就永遠接不上 `food_places`（「這家店我們去過幾次、總共花多少」）。

關鍵取捨：**存原始的 `inv["seller"]`，不是 `simplify_seller()` 的結果。**
`simplify_seller()` 是純函式，讀取時隨時能套；反過來原始值沒存就永遠救不回來
（歷史那批發票就是這樣沒了）。有損轉換一律留到讀取端。
"""
import pytest

import einvoice
from einvoice import simplify_seller
from models import Transaction
from tests.test_core import FakeSession


# ── ① 欄位存在且有 index ────────────────────────────────

def test_transaction_有_seller_欄位():
    assert "seller" in {c.name for c in Transaction.__table__.columns}


def test_seller_可為空():
    """手動記帳 / 固定支出沒有賣方概念，發票也可能抓不到 → 必須 nullable。"""
    assert Transaction.__table__.columns["seller"].nullable is True


def test_seller_有建索引():
    """這個欄位的用途就是 group by / join food_places，沒 index 等於白存。"""
    assert Transaction.__table__.columns["seller"].index is True


# ── ②③④ 寫入契約 ──────────────────────────────────────

SELLER = "全家便利商店股份有限公司"


@pytest.fixture
def fake(monkeypatch):
    s = FakeSession()
    monkeypatch.setattr(einvoice, "SessionLocal", lambda: s)
    return s


def _inv(**kw):
    inv = {
        "invoice_no": "AA00000001",
        "amount": 43,
        "date": "2026-08-29",
        "seller": SELLER,
        "items": [{"name": "禦飯糰", "amount": 43}],
    }
    inv.update(kw)
    return inv


def test_逐品項路徑會存下賣方(fake):
    einvoice._save_invoices([_inv()], source="載具1")
    assert len(fake.added) == 1
    assert fake.added[0].seller == SELLER


def test_同一張發票的每個品項都帶賣方(fake):
    """一張發票拆成多筆 transaction，少帶一筆就是少一次「這家店的消費」。"""
    einvoice._save_invoices([_inv(items=[
        {"name": "禦飯糰", "amount": 30},
        {"name": "茶葉蛋", "amount": 13},
    ])])
    assert [t.seller for t in fake.added] == [SELLER, SELLER]


def test_抓不到明細的保底路徑也會存下賣方(fake):
    """保底那筆用賣方當品名，seller 欄也要存——最不該漏的一條路。"""
    einvoice._save_invoices([_inv(items=[])])
    assert len(fake.added) == 1
    assert fake.added[0].seller == SELLER


def test_存的是原始賣方名不是_simplify_過的(fake):
    """simplify 是有損的：『全家便利商店股份有限公司』→『全家便利商店』。
    存簡化版等於把公司別/分店資訊丟掉，而簡化隨時可以在讀取時再做一次。"""
    einvoice._save_invoices([_inv()])
    assert fake.added[0].seller == SELLER
    assert fake.added[0].seller != simplify_seller(SELLER)


def test_保底路徑的品名簡化不影響_seller_欄(fake):
    """item 可以是精簡名（給人看），seller 一定是原始名（給機器 join）。"""
    einvoice._save_invoices([_inv(items=[])])
    tx = fake.added[0]
    assert tx.item == simplify_seller(SELLER)
    assert tx.seller == SELLER


def test_賣方抓不到時存_None_而不是空字串(fake):
    """空字串會混進 group by 變成一個假的『無名店家』；NULL 才是『不知道』。"""
    einvoice._save_invoices([_inv(seller="")])
    assert fake.added[0].seller is None


def test_seller_不影響既有的_source_契約(fake):
    """回歸：加欄位不能把「這筆是誰花的」弄丟。"""
    einvoice._save_invoices([_inv()], source="載具2")
    assert fake.added[0].source == "載具2"
