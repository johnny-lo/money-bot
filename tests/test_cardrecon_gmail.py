import re
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from cardrecon import gmail

SRC = Path(gmail.__file__).read_text(encoding="utf-8")


def test_唯讀守衛_沒有任何會改信箱的呼叫():
    for bad in (".store(", ".expunge(", ".copy(", ".move(", ".append(", "BODY[]"):
        assert bad not in SRC.replace("BODY.PEEK[]", ""), bad
    assert "readonly=True" in SRC


def test_imap_日期格式不受語系影響():
    assert gmail.imap_date(date(2026, 3, 5)) == "05-Mar-2026"


def test_rawmail_取第一個pdf與去標籤內文():
    m = EmailMessage()
    m["Message-ID"] = "<abc@x>"
    m["From"] = "Bank <spendservice@sinopac.com>"
    m["Subject"] = "消費通知"
    m["Date"] = "Fri, 09 Oct 2026 11:09:22 +0800"
    m.set_content("plain")
    m.add_alternative("<p>親愛的&nbsp;客戶</p><style>x{}</style>", subtype="html")
    m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="octet-stream", filename="a.pdf")
    r = gmail.to_rawmail(m.as_bytes())
    assert r.message_id == "<abc@x>" and r.sender == "spendservice@sinopac.com"
    assert r.subject == "消費通知" and r.received == date(2026, 10, 9)
    assert r.pdf == b"%PDF-1.4 fake"
    assert re.sub(r"\s+", " ", r.text).strip() == "親愛的 客戶"


def test_缺帳密_丟RuntimeError(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    try:
        gmail.fetch("a@b", "x")
    except RuntimeError as e:
        assert "GMAIL_ADDRESS" in str(e)
    else:
        raise AssertionError("應該丟 RuntimeError")
