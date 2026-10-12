import json
import struct
import zlib
from datetime import date

from cardrecon import brand, merchant_ocr, parse, pdf, repo
from cardrecon.types import Bitmap, Charge, Receipt

D1, D2 = date(2026, 9, 8), date(2026, 9, 9)


def C(line_no, amount=3000, card="1111", merchant=None, cd=D1, pd=D2):
    return Charge(source="ctbc_statement", card_last4=card, charge_date=cd, amount=amount, line_no=line_no,
                  post_date=pd, region="TW", merchant=merchant)


def test_列與店名格_用同一個y對位():
    chunks = [(13.2, 901.4, "115/09/08 115/09/09"), (274.3, 901.4, "3,000 1111 TW"),
              (13.2, 891.6, "115/09/08 115/09/10"), (200.2, 891.6, "A 50 1111 TW"),
              (13.2, 881.0, "115/09/08 115/09/10 SHOP.EXAMPLE 690 1111 US TWD 690.00"),
              (13.2, 871.0, "115/09/09 115/09/10"), (274.3, 871.0, "120 1111 TW")]
    cells = [(124.8, 899.5, 60, 8.6, "Im1"), (124.8, 889.7, 60, 8.6, "Im2"),
             (61.9, 869.0, 40, 8.6, "Im9"), (124.8, 860.0, 60, 8.6, "Im3")]
    assert pdf.row_cells(chunks, cells) == [((D1, D2, 3000, "1111"), "Im1"),
                                            ((D1, date(2026, 9, 10), 50, "1111"), "Im2")]


def test_店名對回刷卡_同鍵依序_已有店名不動():
    named = [((D1, D2, 3000, "1111"), "店甲"), ((D1, D2, 3000, "1111"), "店乙"), ((D1, D2, 99, "1111"), None)]
    got = merchant_ocr.assign_by_key([C(5), C(2), C(7, amount=99), C(9, merchant="已有")], named)
    assert got == {2: "店甲", 5: "店乙"}


def test_png_尺寸與黑點():
    bm = Bitmap(width=9, height=2, data=bytes([0b10000000, 0, 0, 0]), one_is_black=True)
    png = merchant_ocr.to_png([bm, bm], scale=2, gap=6)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    assert (w, h) == (18, 2 * (2 * 2 + 6))
    i = png.index(b"IDAT")
    n = struct.unpack(">I", png[i - 4:i])[0]
    raw = zlib.decompress(png[i + 4:i + 4 + n])
    assert len(raw) == (w + 1) * h and raw[1] == 0 and raw[3] == 255     # 第一點黑、第二個放大前的點白


def test_讀名_行數對不上整批放棄_全形轉半形_分批(monkeypatch):
    calls = []

    def fake(prompt, img, mime, schema=None):
        calls.append(img)
        n = 25 if len(calls) == 1 else 4
        return json.dumps({"lines": ["中油ＰＡＹ儲值"] * n})
    monkeypatch.setattr(merchant_ocr, "codex_image", fake)
    bm = Bitmap(width=8, height=1, data=b"\x00", one_is_black=True)
    got = merchant_ocr.read_names([bm] * 30)
    assert len(calls) == 2 and got[:25] == ["中油PAY儲值"] * 25 and got[25:] == [None] * 5
    monkeypatch.setattr(merchant_ocr, "codex_image", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert merchant_ocr.read_names([bm]) == [None]


def test_永豐網路消費通知():
    t = "您永豐信用卡/簽帳金融卡末四碼 1111 於 2026-08-08 19:19 消費台幣10,540，商店名稱:SHOP.EXAMPLE，實際商店名稱請以帳單為準"
    assert parse.parse_sinopac_online(t) == Receipt(paid_date=date(2026, 8, 8), amount=10540, merchant="SHOP.EXAMPLE")
    assert parse.parse_sinopac_online("無關的信") is None
    assert set(parse.RECEIPT_PARSERS) == {"autopass", "sinopac_online"}


def test_品牌建議_丟棄不合法_一批失敗不擋(monkeypatch):
    calls = []

    def fake(prompt, schema=None):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("codex down")
        return json.dumps({"items": [{"i": 0, "brand": "麥當勞"}, {"i": 1, "brand": " "},
                                     {"i": 99, "brand": "X"}, {"i": 2, "brand": "名" * 21}]})
    monkeypatch.setattr(brand, "codex_text", fake)
    raws = [f"店{i}" for i in range(45)]
    got = brand.suggest(raws)
    assert len(calls) == 2 and got == {"店0": "麥當勞"} and "不可信" in calls[0]


def test_顯示與補記用品牌():
    b = {"台灣麥當勞餐廳－123": "麥當勞"}
    assert repo.branded(C(1, merchant="台灣麥當勞餐廳－123"), b).merchant == "麥當勞"
    assert repo.branded(C(1, merchant="別家"), b).merchant == "別家"
    assert repo.branded(C(1), b).merchant is None
    assert repo.transaction_fields(C(1, merchant="台灣麥當勞餐廳－123"), b)["item"] == "麥當勞"
    assert repo.transaction_fields(C(1))["item"] == "信用卡消費（TW）"


class _Q:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows


class _Db:
    def __init__(self, rows): self.rows, self.added, self.commits = rows, [], 0
    def query(self, *a, **k): return _Q(self.rows)
    def add(self, o): self.added.append(o)
    def commit(self): self.commits += 1


def test_MerchantBrand_欄位():
    from models import MerchantBrand
    assert MerchantBrand.__tablename__ == "merchant_brands"
    assert set(MerchantBrand.__table__.columns.keys()) == {"raw", "brand", "created_at"}
    assert MerchantBrand.__table__.c.raw.primary_key


def test_壞檔與錯密碼_店名格回空():
    assert pdf.ctbc_merchant_cells(b"%PDF-1.4 garbage", "A123456789") == []


def test_設定_收據三欄_與批次大小():
    from cardrecon import config
    assert all(len(r) == 3 and r[2] in parse.RECEIPT_PARSERS for r in config.RECEIPT_SOURCES)
    assert config.OCR_BATCH == 25 and config.BRAND_BATCH == 40


def test_set_merchant_by_line_只寫空的_回筆數():
    from types import SimpleNamespace as NS
    rows = [NS(line_no=0, merchant=None), NS(line_no=1, merchant="已有"), NS(line_no=2, merchant="")]
    db = _Db(rows)
    assert repo.set_merchant_by_line(db, "<m>", {0: "甲", 1: "乙", 2: "丙", 9: "丁"}) == 2
    assert [r.merchant for r in rows] == ["甲", "已有", "丙"]
    assert repo.set_merchant_by_line(_Db([]), "<m>", {}) == 0


def test_save_brands_不覆蓋已有():
    db = _Db([("甲", "舊")])                      # brand_map 讀到的是 (raw, brand) 列
    assert repo.save_brands(db, {"甲": "新", "乙": "乙牌"}) == 1
    assert [(o.raw, o.brand) for o in db.added] == [("乙", "乙牌")]


def _mini_pdf(content: bytes, image: bytes, extra_image_dict: bytes = b"") -> bytes:
    """手工拼的最小 PDF（未加密）：一頁、Helvetica、一張 8x1 的 1-bit 遮罩圖 /Im1。"""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 900] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /XObject /Subtype /Image /Width 8 /Height 1 /ImageMask true "
            b"/BitsPerComponent 1 " + extra_image_dict + b"/Length %d >>\nstream\n" % len(image) + image
            + b"\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


_PAGE = (b"BT /F1 10 Tf 13.2 700 Td (115/09/08 115/09/09) Tj ET\n"
         b"BT /F1 10 Tf 274.3 700 Td (3,000 1111 TW) Tj ET\n"
         b"q 60 0 0 8 124.8 698 cm /Im1 Do Q\n")


def test_ctbc_merchant_cells_讀合成PDF_的文字塊與圖片格():
    got = pdf.ctbc_merchant_cells(_mini_pdf(_PAGE, b"\x0f"), "A123456789")
    assert got == [((D1, D2, 3000, "1111"), Bitmap(width=8, height=1, data=b"\x0f", one_is_black=False))]


def test_ctbc_merchant_cells_Decode反轉_一是黑():
    got = pdf.ctbc_merchant_cells(_mini_pdf(_PAGE, b"\x0f", b"/Decode [1 0] "), "A123456789")
    assert [bm.one_is_black for _, bm in got] == [True]
