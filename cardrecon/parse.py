"""純函式：銀行信件/PDF 文字 → Charge / Receipt。版型不認得回空，不丟例外（ingest 記成警告）。"""
import re
from datetime import date

from .types import Charge, Receipt

_UNIC = re.compile(r"/UNIC([0-9A-F]{4})")


def decode_glyph_names(text: str) -> str:
    """中信 PDF 的字型沒有對照表，pypdf 抽出 /UNIC0038 這種字形名；名字就是 Unicode 碼位。"""
    return _UNIC.sub(lambda m: chr(int(m.group(1), 16)), text)


def _amount(s: str) -> int:
    return int(s.replace(",", ""))


def _roc(y: str, m: str, d: str) -> date:
    return date(int(y) + 1911, int(m), int(d))


_SINOPAC_PERIOD = re.compile(r"期間：(\d+)/(\d+)/(\d+)")
_SINOPAC_ROW = re.compile(r"(?:正卡|附卡)\s+(\d{4})\s+(\d+)\s*/\s*(\d+)\s+(\d+)：(\d+)\s+(\S+)\s+NT\$\s*(-?[\d,]+)")


def parse_sinopac(text: str) -> list[Charge]:
    """永豐每日消費通知。年份取「期間：115/10/08」；刷卡月份比期間大＝去年（一月的信裡有十二月的刷卡）。"""
    p = _SINOPAC_PERIOD.search(text)
    if not p:
        return []
    year, period_month = int(p[1]) + 1911, int(p[2])
    out = []
    for line_no, m in enumerate(_SINOPAC_ROW.finditer(text)):
        amount = _amount(m[7])
        if amount <= 0:
            continue
        month = int(m[2])
        out.append(Charge(source="sinopac_daily", card_last4=m[1],
                          charge_date=date(year - 1 if month > period_month else year, month, int(m[3])),
                          amount=amount, line_no=line_no, charge_time=f"{int(m[4]):02d}:{m[5]}", region=m[6]))
    return out


_CTBC_ONE_LINE = re.compile(r"^(\d{3})/(\d\d)/(\d\d) (\d{3})/(\d\d)/(\d\d) (.+?) (-?[\d,]+) (\d{4}) ([A-Z]{2})\b")
_CTBC_DATES = re.compile(r"^(\d{3})/(\d\d)/(\d\d) (\d{3})/(\d\d)/(\d\d)$")
_CTBC_AMOUNT = re.compile(r"^(?:([A-Z]) )?(-?[\d,]+) (\d{4}) ([A-Z]{2})$")


def parse_ctbc(text: str) -> list[Charge]:
    """中信月帳單。兩種版型：同一行帶英文店名；或日期一行、下一行「[支付代碼] 金額 卡號 國別」（中文店名抽不出來）。"""
    lines = [ln.strip() for ln in decode_glyph_names(text).split("\n")]
    out, line_no = [], 0
    for i, ln in enumerate(lines):
        m = _CTBC_ONE_LINE.match(ln)
        if m:
            d, merchant, pay, amt, card, region = m.groups()[:6], m[7].strip(), None, m[8], m[9], m[10]
        else:
            m = _CTBC_DATES.match(ln)
            a = _CTBC_AMOUNT.match(lines[i + 1]) if m and i + 1 < len(lines) else None
            if not a:
                continue
            d, merchant, pay, amt, card, region = m.groups(), None, a[1], a[2], a[3], a[4]
        amount, n = _amount(amt), line_no
        line_no += 1
        if amount <= 0:
            continue
        out.append(Charge(source="ctbc_statement", card_last4=card, charge_date=_roc(*d[:3]),
                          post_date=_roc(*d[3:6]), amount=amount, line_no=n, region=region,
                          merchant=merchant or None, pay_method=pay))
    return out


_AP_AMOUNT = re.compile(r"付款金額\s*([\d,]+)\s*元")
_AP_TIME = re.compile(r"付款時間：\s*(\d{4})\.(\d{2})\.(\d{2})")
_AP_MERCHANT = re.compile(r"付款成功\s*[\d,]+\s*元\s*(.+?)\s+[0-9a-f]{8}-[0-9a-f]{4}-")


def parse_autopass(text: str) -> Receipt | None:
    a, t, m = _AP_AMOUNT.search(text), _AP_TIME.search(text), _AP_MERCHANT.search(text)
    if not (a and t and m):
        return None
    return Receipt(paid_date=date(int(t[1]), int(t[2]), int(t[3])), amount=_amount(a[1]), merchant=m[1].strip())


PARSERS = {"sinopac_daily": parse_sinopac, "ctbc_statement": parse_ctbc}
