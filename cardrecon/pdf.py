"""加密 PDF → 文字。銀行預設密碼是身分證字號（英文大寫）。"""
import io
import re

from pypdf import PdfReader

from .parse import _CTBC_AMOUNT, _CTBC_DATES, _roc, decode_glyph_names
from .types import Bitmap


def extract_text(data: bytes, password: str) -> str | None:
    """解不開或壞檔回 None（呼叫端計數成「解密失敗」），不丟例外。"""
    try:
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted and not r.decrypt(password.strip().upper()):
            return None
        return "\n".join(p.extract_text() or "" for p in r.pages)
    except Exception:
        return None


_CELL = re.compile(r"([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm /(Im\d+) Do")
_ROW_Y_TOL = 1.0                     # 同一列的文字塊 y 差距（點）
_NAME_X = (120, 130)                 # 店名欄的 x 範圍
_NAME_DY = 4                         # 店名格的 y 落在列文字 y−4 到 y 之間


def row_cells(chunks, cells):
    """純函式：把「日期塊＋金額塊」的列對上店名圖片格。

    chunks＝[(x, y, text)]、cells＝[(x, y, w, h, name)]。中信的中文店名是 1-bit 圖片，
    圖片格比同一列文字低 2 點上下，所以用 y 對位；對位不到剛好一格的列不收（寧缺勿錯）。
    回 [((刷卡日, 入帳日, 金額, 卡號), 圖片名)]，照列出現的順序。
    """
    out = []
    for x, y, text in chunks:
        d = _CTBC_DATES.match(text) if x < 40 else None
        if not d:
            continue
        a = next((m for cx, cy, t in chunks if abs(cy - y) < _ROW_Y_TOL and (m := _CTBC_AMOUNT.match(t))), None)
        if not a:
            continue
        hit = [c for c in cells if _NAME_X[0] <= c[0] <= _NAME_X[1] and y - _NAME_DY <= c[1] <= y]
        if len(hit) != 1:
            continue
        try:
            key = (_roc(*d.groups()[:3]), _roc(*d.groups()[3:]), int(a[2].replace(",", "")), a[3])
        except ValueError:
            continue
        out.append((key, hit[0][4]))
    return out


def _bitmap(xobj) -> Bitmap | None:
    """PDF 圖片物件 → Bitmap；不是 1-bit 就回 None。ImageMask 與 DeviceGray 都是 Decode [1 0] 時 1 才是黑。"""
    xobj = xobj.get_object()
    mask = bool(xobj.get("/ImageMask", False))
    if not mask and int(xobj.get("/BitsPerComponent", 8)) != 1:
        return None
    w, h = int(xobj["/Width"]), int(xobj["/Height"])
    data = xobj.get_data()
    if len(data) < ((w + 7) // 8) * h:
        return None
    decode = [int(v) for v in xobj.get("/Decode", [0, 1])]
    return Bitmap(width=w, height=h, data=bytes(data), one_is_black=decode == [1, 0])


def ctbc_merchant_cells(data: bytes, password: str) -> list[tuple[tuple, Bitmap]]:
    """中信月帳單：每一列的 (刷卡日, 入帳日, 金額, 卡號) 與它的店名圖片。壞檔或解不開回 []，不丟例外。"""
    try:
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted and not r.decrypt(password.strip().upper()):
            return []
        out = []
        for page in r.pages:
            chunks = []

            def visit(text, cm, tm, font_dict, font_size):
                t = decode_glyph_names(text).strip()
                if t:
                    chunks.append((tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5], t))
            page.extract_text(visitor_text=visit)
            contents = page.get_contents()
            if contents is None:
                continue
            cells = [(float(m[3]), float(m[4]), float(m[1]), float(m[2]), m[5])
                     for m in _CELL.finditer(contents.get_data().decode("latin-1"))]
            res = page.get("/Resources")
            xobjects = res.get_object().get("/XObject") if res is not None else None
            xobjects = xobjects.get_object() if xobjects is not None else {}
            for key, name in row_cells(chunks, cells):
                ref = xobjects.get(f"/{name}")
                bm = _bitmap(ref) if ref is not None else None
                if bm is not None:
                    out.append((key, bm))
        return out
    except Exception:
        return []
