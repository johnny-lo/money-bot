from datetime import date

from cardrecon import parse

SINOPAC = """期間：115/10/08
親愛的客戶您好：
卡別 卡號末四碼 消費日期 消費時間 消費地區 消費金額
正卡 1234 10 / 08 09：45 US NT$ 380
附卡 5678 10 / 08 23：12 TW NT$ 1,253
正卡 1234 10 / 08 23：30 TW NT$ -50
"""


def test_永豐_逐筆():
    got = parse.parse_sinopac(SINOPAC)
    assert [(c.card_last4, c.charge_date, c.charge_time, c.region, c.amount, c.line_no) for c in got] == [
        ("1234", date(2026, 10, 8), "09:45", "US", 380, 0),
        ("5678", date(2026, 10, 8), "23:12", "TW", 1253, 1),
    ]
    assert all(c.source == "sinopac_daily" and c.merchant is None for c in got)


def test_永豐_跨年_十二月的刷卡在一月的通知裡():
    text = "期間：116/01/01\n正卡 1234 12 / 31 23：50 TW NT$ 99\n正卡 1234 01 / 01 00：10 TW NT$ 88\n"
    got = parse.parse_sinopac(text)
    assert [c.charge_date for c in got] == [date(2026, 12, 31), date(2027, 1, 1)]


def test_永豐_版型不認得_回空():
    assert parse.parse_sinopac("隨便一段字") == []


def test_字形名還原():
    assert parse.decode_glyph_names("/UNIC0031/UNIC0031/UNIC0035/UNIC002F") == "115/"


CTBC = "\n".join([
    "/UNIC0031/UNIC0031/UNIC0035/UNIC002F/UNIC0030/UNIC0038/UNIC002F/UNIC0030/UNIC0035 115/08/07 ACME *STREAMING SUB 450 1111 US TWD 690.00",
    "115/09/06 115/09/09",
    "A 160 1111 TW",
    "115/09/03 115/09/08",
    "1,400 2222 TW",
    "115/09/13 12,345 6,789 0 12,345 0 +6,789",
    "115/09/21 115/09/22 PAYMENT -5,000 1111 TW",
])


def test_中信_兩種版型():
    got = parse.parse_ctbc(CTBC)
    rows = [(c.charge_date, c.post_date, c.merchant, c.pay_method, c.amount, c.card_last4, c.region) for c in got]
    assert rows == [
        (date(2026, 8, 5), date(2026, 8, 7), "ACME *STREAMING SUB", None, 450, "1111", "US"),
        (date(2026, 9, 6), date(2026, 9, 9), None, "A", 160, "1111", "TW"),
        (date(2026, 9, 3), date(2026, 9, 8), None, None, 1400, "2222", "TW"),
    ]
    assert [c.line_no for c in got] == [0, 1, 2]           # 負數那行佔 3 號但被丟掉
    assert all(c.source == "ctbc_statement" for c in got)


def test_中信_版型不認得_回空():
    assert parse.parse_ctbc("x\ny\n") == []


AUTOPASS = ("車麻吉 車牌 ABC-0000 路邊停車訂單 付款成功 80元 某某市路邊停車費 "
            "00000000-0000-4000-8000-000000000000 繳費單號 X 停車日期 2026.05.02 80元 "
            "付款金額 80元 付款通路：車麻吉 付款時間：2026.05.03 09:30 客服小幫手")


def test_autopass_收據():
    r = parse.parse_autopass(AUTOPASS)
    assert (r.paid_date, r.amount, r.merchant) == (date(2026, 5, 3), 80, "某某市路邊停車費")


def test_autopass_不認得_回None():
    assert parse.parse_autopass("別的信") is None


def test_parsers_對照表():
    assert parse.PARSERS == {"sinopac_daily": parse.parse_sinopac, "ctbc_statement": parse.parse_ctbc}
