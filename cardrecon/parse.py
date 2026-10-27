"""純函式：銀行信件/PDF 文字 → Charge / Receipt。版型不認得回空，不丟例外（ingest 記成警告）。"""
import re
import unicodedata
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
        try:
            charge_date = date(year - 1 if month > period_month else year, month, int(m[3]))
        except ValueError:
            continue                                        # 日期不存在：丟這一筆，行號照佔
        out.append(Charge(source="sinopac_daily", card_last4=m[1], charge_date=charge_date,
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
        try:
            charge_date, post_date = _roc(*d[:3]), _roc(*d[3:6])
        except ValueError:
            continue                                        # 日期不存在：丟這一筆，行號照佔
        out.append(Charge(source="ctbc_statement", card_last4=card, charge_date=charge_date,
                          post_date=post_date, amount=amount, line_no=n, region=region,
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


_SP_ONLINE = re.compile(r"於 (\d{4})-(\d\d)-(\d\d) \d\d:\d\d 消費台幣([\d,]+)，商店名稱:(.+?)，")
_SP_CARD = re.compile(r"末四碼\s*(\d{4})")


def parse_sinopac_online(text: str) -> Receipt | None:
    """永豐網路消費通知（CardAuthService@sinopac.com）：內文寫了商店名稱，當收據用來補店名。
    「末四碼 NNNN」一併帶出，enrich 才不會把店名套到同金額、日期相近的別張卡。"""
    m = _SP_ONLINE.search(text)
    if not m:
        return None
    try:
        paid = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    card = _SP_CARD.search(text)
    return Receipt(paid_date=paid, amount=_amount(m[4]), merchant=m[5].strip(), card_last4=card[1] if card else None)


_CTBC_LINE_AMOUNT = re.compile(r"^NT\$\s*([\d,]+)$")
_CTBC_LINE_CARD = re.compile(r"^\d{4}$")
_CTBC_LINE_TIME = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})$")


def _ctbc_line_value(texts: list[str], label: str) -> str | None:
    try:
        index = texts.index(label)
    except ValueError:
        return None
    if index + 1 >= len(texts):
        return None
    value = texts[index + 1]
    return value if isinstance(value, str) else None


def foreign_amount(texts: list[str]) -> bool:
    """判斷通知是否包含外幣金額欄位。"""
    return "外幣金額：" in texts


def parse_ctbc_line(texts: list[str]) -> Charge | None:
    """解析一則已攤平的中信 LINE 消費通知。"""
    if foreign_amount(texts):
        return None

    amount_match = next(
        (match for text in texts if isinstance(text, str)
         and (match := _CTBC_LINE_AMOUNT.fullmatch(text))),
        None,
    )
    card_last4 = _ctbc_line_value(texts, "卡末四碼：")
    time_text = _ctbc_line_value(texts, "交易時間：")
    time_match = _CTBC_LINE_TIME.fullmatch(time_text) if time_text else None
    if not amount_match or not card_last4 or not _CTBC_LINE_CARD.fullmatch(card_last4) or not time_match:
        return None

    try:
        amount = _amount(amount_match[1])
        charge_date = date(int(time_match[1]), int(time_match[2]), int(time_match[3]))
        hour, minute = int(time_match[4]), int(time_match[5])
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None
    except ValueError:
        return None
    if amount <= 0:
        return None

    merchant_value = _ctbc_line_value(texts, "商店名稱：")
    merchant = unicodedata.normalize("NFKC", merchant_value).strip() if merchant_value else None
    merchant = merchant or None
    pay_method = _ctbc_line_value(texts, "交易類型：") or None
    merchant_type = _ctbc_line_value(texts, "商店類型：") or None
    return Charge(
        source="ctbc_line",
        card_last4=card_last4,
        charge_date=charge_date,
        charge_time=f"{hour:02d}:{minute:02d}",
        amount=amount,
        merchant=merchant,
        pay_method=pay_method,
        merchant_type=merchant_type,
        line_no=0,
        region=None,
        post_date=None,
    )


RECEIPT_PARSERS = {"autopass": parse_autopass, "sinopac_online": parse_sinopac_online}
PARSERS = {"sinopac_daily": parse_sinopac, "ctbc_statement": parse_ctbc}
