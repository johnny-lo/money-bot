"""Gmail IMAP 唯讀抓信。唯讀是硬規矩：select readonly=True、只用 BODY.PEEK[]（守衛測試掃原始碼）。"""
import email
import email.header
import email.utils
import imaplib
import os
import re
from datetime import date

from app_secrets import get_secret

from .types import RawMail

HOST = "imap.gmail.com"
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def imap_date(d: date) -> str:
    """IMAP SINCE 要英文月份縮寫；不用 strftime（%b 隨語系變）。"""
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _decode(s: str | None) -> str:
    return str(email.header.make_header(email.header.decode_header(s or "")))


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?s)<(style|script).*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"(&nbsp;|\s)+", " ", s)


def to_rawmail(raw: bytes) -> RawMail:
    m = email.message_from_bytes(raw)
    pdf, html, plain = None, None, None
    for p in m.walk():
        if p.is_multipart():
            continue
        data = p.get_payload(decode=True) or b""
        if pdf is None and data.startswith(b"%PDF"):
            pdf = data
        elif p.get_content_type() == "text/html" and html is None and not p.get_filename():
            html = data.decode(p.get_content_charset() or "utf-8", "replace")
        elif p.get_content_type() == "text/plain" and plain is None and not p.get_filename():
            plain = data.decode(p.get_content_charset() or "utf-8", "replace")
    try:
        received = email.utils.parsedate_to_datetime(m["Date"]).date()
    except Exception:
        received = None
    return RawMail(message_id=(m["Message-ID"] or "").strip(),
                   sender=email.utils.parseaddr(_decode(m["From"]))[1].lower(),
                   subject=_decode(m["Subject"]), received=received, pdf=pdf,
                   text=_html_to_text(html) if html is not None else (plain or ""))


def _all_mail(M) -> str:
    for f in M.list()[1]:
        if b"\\All" in f:
            return re.search(r'"([^"]+)"$', f.decode()).group(1)
    raise RuntimeError("找不到 Gmail「所有郵件」資料夾")


def fetch(sender: str, subject_kw: str, since: date | None = None) -> list[RawMail]:
    addr = (os.getenv("GMAIL_ADDRESS") or "").strip()
    pw = get_secret("GMAIL_APP_PASSWORD")
    if not addr or not pw:
        raise RuntimeError("缺 GMAIL_ADDRESS 環境變數或 gmail_app_password secret")
    M = imaplib.IMAP4_SSL(HOST)
    try:
        M.login(addr, pw.replace(" ", ""))
        M.select(f'"{_all_mail(M)}"', readonly=True)
        crit = ["FROM", sender] + (["SINCE", imap_date(since)] if since else []) + ["SUBJECT"]
        M.literal = subject_kw.encode()          # 中文主旨走 literal，接在最後一個參數 SUBJECT 後面
        uids = M.uid("search", "CHARSET", "UTF-8", *crit)[1][0].split()
        return [to_rawmail(M.uid("fetch", u, "(BODY.PEEK[])")[1][0][1]) for u in uids]
    finally:
        try:
            M.logout()
        except Exception:
            pass
