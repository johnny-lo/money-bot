import io

from pypdf import PdfWriter

from cardrecon import pdf


def _encrypted(pw: str) -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    w.encrypt(pw, algorithm="AES-128")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_正確密碼_回字串_小寫身分證也會轉大寫():
    assert pdf.extract_text(_encrypted("A123456789"), "a123456789") == ""


def test_密碼錯_回None():
    assert pdf.extract_text(_encrypted("A123456789"), "B987654321") is None


def test_壞檔_回None():
    assert pdf.extract_text(b"%PDF-1.4 garbage", "A123456789") is None
