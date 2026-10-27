from dataclasses import replace
from datetime import date, time

import pytest

import codex_cli
from cardrecon import ingest
from cardrecon.types import Bitmap, Charge, RawMail, Receipt, TxGroup
from lineinbox import repo as line_repo
from lineinbox.types import ListenerState

TODAY = date(2026, 10, 18)


def ch(d, amount, n=0, src="sinopac_daily", card="1234"):
    return Charge(source=src, card_last4=card, charge_date=d, amount=amount, line_no=n)


@pytest.fixture(autouse=True)
def codex_calls(monkeypatch):
    """ingest 的流程測試一律不得真的 shell 出 codex：會出網，在已登入的容器還會卡到 180 秒逾時。
    _soft／brand.suggest 都會吞例外，光丟 AssertionError 會被吞掉 → 一併記帳，測試結束再驗一次。"""
    calls = []

    def boom(*a, **k):
        calls.append(a[:1])
        raise AssertionError("測試不得呼叫真的 codex")
    monkeypatch.setattr(codex_cli, "_codex_exec", boom)
    yield calls
    assert calls == [], f"測試走到了真的 codex：{len(calls)} 次"


class FakeRepo:
    """記憶體版 repo：只實作 ingest 用到的函式。"""
    def __init__(self, existing=()):
        self.rows = {}           # id -> dict(charge, status, batch, key)
        for c, status, batch in existing:
            self._add(c, status, batch)
    def _add(self, c, status="unmatched", batch=None):
        i = len(self.rows) + 1
        self.rows[i] = dict(c=c, status=status, batch=batch, key=None, msg=None)
        return i
    def has_source(self, db, source): return any(r["c"].source == source for r in self.rows.values())
    def max_page(self, db, day):
        pages = [int(r["batch"].rsplit("-", 1)[1]) for r in self.rows.values()
                 if r["batch"] and r["batch"].rsplit("-", 1)[0] == day]
        return max(pages, default=0)
    def upsert_charges(self, db, mid, charges):
        new = 0
        for c in charges:
            if any(r["msg"] == mid and r["c"].line_no == c.line_no for r in self.rows.values()):
                continue
            self.rows[self._add(c)]["msg"] = mid
            new += 1
        return new
    def pending(self, db, until):
        return [(i, r["c"]) for i, r in self.rows.items() if r["status"] == "unmatched" and r["c"].charge_date <= until]
    def unlisted(self, db, until, since):
        return [(i, c) for i, c in self.pending(db, until) if self.rows[i]["batch"] is None and c.charge_date >= since]
    def set_merchant(self, db, m):
        self.merchants = m
        for i, name in m.items():
            self.rows[i]["c"] = replace(self.rows[i]["c"], merchant=name)
    def missing_merchant_lines(self, db, mid):
        return {r["c"].line_no for r in self.rows.values() if r["msg"] == mid and not r["c"].merchant}
    def set_merchant_by_line(self, db, mid, mapping):
        n = 0
        for r in self.rows.values():
            if r["msg"] == mid and not r["c"].merchant and r["c"].line_no in mapping:
                r["c"] = replace(r["c"], merchant=mapping[r["c"].line_no])
                n += 1
        return n
    def missing_merchant(self, db): return [(i, r["c"]) for i, r in self.rows.items() if not r["c"].merchant]
    brands = {}
    def brand_map(self, db): return dict(self.brands)
    def missing_brands(self, db):
        return sorted({r["c"].merchant for r in self.rows.values() if r["c"].merchant and r["c"].merchant not in self.brands})
    def save_brands(self, db, m):
        new = {k: v for k, v in m.items() if k not in self.brands}
        self.brands = {**self.brands, **new}
        return len(new)
    def used_group_keys(self, db): return set()
    def load_groups(self, db, since): return self.groups
    def mark_matched(self, db, m):
        for i, k in m.items():
            self.rows[i].update(status="matched", key=k)
    def all_charges(self, db): return [r["c"] for r in self.rows.values()]
    def unlist(self, db):
        n = 0
        for r in self.rows.values():
            if r["status"] == "unmatched" and r["batch"] is not None:
                r["batch"] = None
                n += 1
        return n
    def assign_batch(self, db, ids, batch):
        for i in ids:
            self.rows[i]["batch"] = batch
    def weekly_line_stats(self, db, since): return (0, 0)


def _wire(monkeypatch, fake, mails, texts):
    monkeypatch.setattr(ingest, "repo", fake)
    monkeypatch.setattr(ingest, "get_secret", lambda k: "A123456789")
    monkeypatch.setattr(ingest.gmail, "fetch", lambda sender, kw, since=None: mails.get(sender, []))
    monkeypatch.setattr(ingest.pdf, "extract_text", lambda data, pw: texts.get(data))
    # 讀圖與品牌是 codex：預設全擋成空結果，要驗它們的測試自己再覆蓋
    monkeypatch.setattr(ingest.pdf, "ctbc_merchant_cells", lambda data, pw: [])
    monkeypatch.setattr(ingest.merchant_ocr, "read_names", lambda bms: [None] * len(bms))
    monkeypatch.setattr(ingest.brand, "suggest", lambda raws: {})
    # LINE listener 狀態在 line_listener_state 表：預設當作沒有列，不連 DB
    monkeypatch.setattr(line_repo, "listener_state", lambda db: None)


def mail(mid, pdf=b"x", text=""):
    return RawMail(message_id=mid, sender="s", subject="", received=None, pdf=pdf, text=text)


def test_整條流程_配對_分頁_解密失敗與解析零筆計數(monkeypatch):
    fake = FakeRepo()
    fake.groups = [TxGroup("INV", date(2026, 10, 1), 500)]
    mails = {"spendservice@sinopac.com": [mail("<a>", b"A"), mail("<b>", b"BAD"), mail("<c>", None)],
             "ebill@estats.ctbcbank.com": [mail("<d>", b"EMPTY")]}
    texts = {b"A": "a", b"EMPTY": "e"}
    _wire(monkeypatch, fake, mails, texts)
    charges = [ch(date(2026, 10, 1), 500, 0)] + [ch(date(2026, 10, 2), 10 + i, i + 1) for i in range(26)] \
        + [ch(date(2026, 10, 17), 99, 30), ch(date(2026, 2, 21), 77, 31)]
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: charges if t == "a" else [],
                                                   "ctbc_statement": lambda t: []})
    res = ingest.run_weekly(TODAY)
    assert (res.failed_mails, res.unparsed_mails) == (1, 2)         # BAD 解不開；<c> 沒附件、<d> 解析 0 筆
    assert [b for b, _, _ in res.pages] == ["2026-10-18-1", "2026-10-18-2"]
    assert [g for _, g, _ in res.pages] == ["small", "small"]     # 10~35 元皆為小額
    assert [len(items) for _, _, items in res.pages] == [25, 1]        # 500 配到；10/17 太新；2/21 早於 LIST_FROM
    assert res.total == sum(10 + i for i in range(26))
    assert fake.rows[1]["status"] == "matched"


def test_已列過的_下週不再列(monkeypatch):
    fake = FakeRepo(existing=[(ch(date(2026, 10, 1), 300), "unmatched", "2026-10-11-1")])
    fake.groups = []
    _wire(monkeypatch, fake, {}, {})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    assert ingest.run_weekly(TODAY).pages == []


def _seen_by_sender(monkeypatch, fake):
    seen = {}
    _wire(monkeypatch, fake, {}, {})
    monkeypatch.setattr(ingest.gmail, "fetch", lambda s, k, since=None: seen.setdefault(s, []).append(since) or [])
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    return seen


def test_第一次抓全部_之後回看60天(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    seen = _seen_by_sender(monkeypatch, fake)
    ingest.run_weekly(TODAY)
    assert {s for v in seen.values() for s in v} == {None}
    fake._add(ch(date(2026, 10, 1), 1, src="sinopac_daily"))
    fake._add(ch(date(2026, 10, 1), 1, src="ctbc_statement"))
    seen.clear()
    ingest.run_weekly(TODAY)
    assert {s for v in seen.values() for s in v} == {date(2026, 8, 19)}


def test_部分首跑_沒存過的來源仍抓全部(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    fake._add(ch(date(2026, 10, 1), 1, src="sinopac_daily"))
    seen = _seen_by_sender(monkeypatch, fake)
    ingest.run_weekly(TODAY)
    (sinopac, _), (ctbc, _) = ingest.config.CARD_SOURCES.values()
    assert seen[sinopac] == [date(2026, 8, 19)]
    assert seen[ctbc][0] is None
    receipt_since = [v for k, v in seen.items() if k not in (sinopac, ctbc)]
    assert receipt_since and all(s is None for v in receipt_since for s in v)


def test_同日再跑_批次接續編號(monkeypatch):
    day = TODAY.isoformat()
    fake = FakeRepo(existing=[(ch(date(2026, 10, 1), 1, 0), "unmatched", f"{day}-1"),
                              (ch(date(2026, 10, 1), 2, 1), "unmatched", f"{day}-2")])
    fake.groups = []
    _wire(monkeypatch, fake, {"spendservice@sinopac.com": [mail("<n>", b"A")]}, {b"A": "a"})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [ch(date(2026, 10, 2), 7, 5)],
                                                   "ctbc_statement": lambda t: []})
    res = ingest.run_weekly(TODAY)
    assert [b for b, _, _ in res.pages] == [f"{day}-3"]


def test_收據補店名(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    ap = "cs@autopass.xyz"
    _wire(monkeypatch, fake, {ap: [mail("<r>", None, "收據")]}, {})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    monkeypatch.setattr(ingest.parse, "RECEIPT_PARSERS",
                        {"autopass": lambda t: Receipt(date(2026, 10, 1), 110, "停車費"), "sinopac_online": lambda t: None})
    fake._add(ch(date(2026, 10, 1), 110))
    ingest.run_weekly(TODAY)
    assert fake.merchants == {1: "停車費"}


def test_缺身分證_丟RuntimeError(monkeypatch):
    _wire(monkeypatch, FakeRepo(), {}, {})
    monkeypatch.setattr(ingest, "get_secret", lambda k: None)
    try:
        ingest.run_weekly(TODAY)
    except RuntimeError as e:
        assert "national_id" in str(e)
    else:
        raise AssertionError


def test_分組各自分頁_批次號跨組連續(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    _wire(monkeypatch, fake, {"spendservice@sinopac.com": [mail("<a>", b"A")]}, {b"A": "a"})
    monkeypatch.setattr(ingest.config, "PAGE_SIZE", 2)
    charges = [ch(date(2026, 10, 2), 1000, 0), ch(date(2026, 10, 2), 50, 1), ch(date(2026, 10, 2), 60, 2),
               ch(date(2026, 10, 2), 70, 3), ch(date(2026, 10, 2), 500, 4)]
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: charges, "ctbc_statement": lambda t: []})
    res = ingest.run_weekly(TODAY)
    assert [(b, g, [i for i, _, _ in items]) for b, g, items in res.pages] == [
        ("2026-10-18-1", "small", [2, 3]), ("2026-10-18-2", "small", [4]),
        ("2026-10-18-3", "other", [1, 5])]
    assert all(h is None for _, _, items in res.pages for _, _, h in items)
    assert res.total == sum(c.amount for c in charges)


def test_relist_重列未處理的_不碰gmail也不要secret(monkeypatch):
    day = TODAY.isoformat()
    fake = FakeRepo(existing=[(ch(date(2026, 10, 1), 300, 0), "unmatched", f"{day}-1"),
                              (ch(date(2026, 10, 1), 400, 1), "ignored", f"{day}-1"),
                              (ch(date(2026, 10, 1), 20, 2), "unmatched", f"{day}-1")])
    fake.groups = []
    _wire(monkeypatch, fake, {}, {})
    def boom(*a, **k): raise AssertionError("relist 不該碰 Gmail／secret")
    monkeypatch.setattr(ingest.gmail, "fetch", boom)
    monkeypatch.setattr(ingest, "get_secret", boom)
    res = ingest.relist(TODAY)
    assert [(b, g, [i for i, _, _ in items]) for b, g, items in res.pages] == [
        (f"{day}-2", "small", [3]), (f"{day}-3", "other", [1])]
    assert fake.rows[2]["batch"] == f"{day}-1" and fake.rows[2]["status"] == "ignored"
    assert res.total == 320


def test_relist_同日舊批次全未處理_新批次號不與舊的重複(monkeypatch):
    day = TODAY.isoformat()
    fake = FakeRepo(existing=[(ch(date(2026, 10, 1), 300, 0), "unmatched", f"{day}-1"),
                              (ch(date(2026, 10, 1), 400, 1), "unmatched", f"{day}-2"),
                              (ch(date(2026, 10, 1), 500, 2), "unmatched", f"{day}-3")])
    fake.groups = []
    _wire(monkeypatch, fake, {}, {})
    res = ingest.relist(TODAY)
    assert [b for b, _, _ in res.pages] == [f"{day}-4"]


def test_永豐網路消費通知_補店名(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    sp = "CardAuthService@sinopac.com"
    note = "您永豐信用卡末四碼 1234 於 2026-10-01 19:19 消費台幣10,540，商店名稱:SHOP.EXAMPLE，實際商店名稱請以帳單為準"
    _wire(monkeypatch, fake, {sp: [mail("<n>", None, note)]}, {})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    fake._add(ch(date(2026, 10, 1), 10540))
    ingest.run_weekly(TODAY)
    assert fake.merchants == {1: "SHOP.EXAMPLE"}


def test_中信每封upsert後讀圖補店名_只補缺的_回報排序(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    _wire(monkeypatch, fake, {"ebill@estats.ctbcbank.com": [mail("<c>", b"C")]}, {b"C": "c"})
    d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
    charges = [replace(ch(d1, 3000, 0, "ctbc_statement"), post_date=d2, card_last4="1111"),
               replace(ch(d1, 50, 1, "ctbc_statement"), post_date=d2, card_last4="1111", merchant="SHOP.EXAMPLE")]
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: charges})
    bm = Bitmap(width=8, height=1, data=b"\x00", one_is_black=True)
    cells = [((d1, d2, 3000, "1111"), bm), ((d1, d2, 50, "1111"), bm)]
    monkeypatch.setattr(ingest.pdf, "ctbc_merchant_cells", lambda data, pw: cells)
    monkeypatch.setattr(ingest.merchant_ocr, "read_names", lambda bms: ["某某店", "不該覆蓋"][:len(bms)])
    monkeypatch.setattr(ingest.brand, "suggest", lambda raws: {})
    ingest.run_weekly(TODAY)
    assert [r["c"].merchant for r in fake.rows.values()] == ["某某店", "SHOP.EXAMPLE"]


def test_讀圖與品牌例外_只警告不擋清單(monkeypatch, capsys):
    fake = FakeRepo()
    fake.groups = []
    _wire(monkeypatch, fake, {"ebill@estats.ctbcbank.com": [mail("<c>", b"C")]}, {b"C": "c"})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [],
                                                   "ctbc_statement": lambda t: [ch(date(2026, 10, 1), 700, 0, "ctbc_statement")]})
    def boom(*a, **k): raise RuntimeError("codex down")
    monkeypatch.setattr(ingest.pdf, "ctbc_merchant_cells", boom)
    monkeypatch.setattr(ingest.brand, "suggest", boom)
    fake._add(ch(date(2026, 10, 1), 20, 5), )
    fake.rows[1]["c"] = replace(fake.rows[1]["c"], merchant="某店")           # 讓 _fill_brands 真的去問
    res = ingest.run_weekly(TODAY)
    assert [len(items) for _, _, items in res.pages] == [1, 1]
    assert capsys.readouterr().out.count("⚠️") >= 2


def test_清單與補記用品牌_原名留著(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    fake._add(replace(ch(date(2026, 10, 1), 700), merchant="台灣某某餐廳－123"))
    _wire(monkeypatch, fake, {}, {})
    monkeypatch.setattr(ingest.brand, "suggest", lambda raws: {r: "某某" for r in raws})
    res = ingest.relist(TODAY)
    assert fake.brands == {"台灣某某餐廳－123": "某某"}
    assert [c.merchant for _, _, items in res.pages for _, c, _ in items] == ["某某"]
    assert fake.rows[1]["c"].merchant == "台灣某某餐廳－123"


def test_backfill_merchants_回計數(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    _wire(monkeypatch, fake, {"ebill@estats.ctbcbank.com": [mail("<c>", b"C"), mail("<x>", None)],
                              "cs@autopass.xyz": [mail("<r>", None, "收據")]}, {b"C": "c"})
    d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
    c0 = replace(ch(d1, 3000, 0, "ctbc_statement"), post_date=d2, card_last4="1111")
    fake.upsert_charges(None, "<c>", [c0])
    fake._add(ch(d1, 110, 0))
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: [c0]})
    monkeypatch.setattr(ingest.parse, "RECEIPT_PARSERS",
                        {"autopass": lambda t: Receipt(d1, 110, "停車費"), "sinopac_online": lambda t: None})
    bm = Bitmap(width=8, height=1, data=b"\x00", one_is_black=True)
    monkeypatch.setattr(ingest.pdf, "ctbc_merchant_cells", lambda data, pw: [((d1, d2, 3000, "1111"), bm)])
    monkeypatch.setattr(ingest.merchant_ocr, "read_names", lambda bms: ["某某店"])
    monkeypatch.setattr(ingest.brand, "suggest", lambda raws: {"某某店": "某某"})
    assert ingest.backfill_merchants(TODAY) == {"ocr": 1, "receipts": 1, "brands": 1}
    assert ingest.backfill_merchants(TODAY) == {"ocr": 0, "receipts": 0, "brands": 0}      # 冪等：已補的不再動


def test_守衛_有店名的流程不走到真的codex(monkeypatch, codex_calls):
    """有店名的刷卡會讓 _fill_brands 去問品牌；_wire 的預設 stub 要擋在 codex 之前。"""
    fake = FakeRepo()
    fake.groups = []
    fake._add(replace(ch(date(2026, 10, 1), 700), merchant="某某店"))
    _wire(monkeypatch, fake, {}, {})
    res = ingest.relist(TODAY)
    assert [len(items) for _, _, items in res.pages] == [1]
    assert codex_calls == []


def _ctbc_two_rows(monkeypatch, fake, cells_for):
    """兩列中信刷卡：第 0 列缺店名、第 1 列已有店名。cells_for(k0, k1, bm) 決定圖片格有哪些鍵。"""
    _wire(monkeypatch, fake, {"ebill@estats.ctbcbank.com": [mail("<c>", b"C")]}, {b"C": "c"})
    d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
    charges = [replace(ch(d1, 3000, 0, "ctbc_statement"), post_date=d2, card_last4="1111"),
               replace(ch(d1, 50, 1, "ctbc_statement"), post_date=d2, card_last4="1111", merchant="SHOP.EXAMPLE")]
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: charges})
    bm = Bitmap(width=8, height=1, data=b"\x00", one_is_black=True)
    cells = cells_for((d1, d2, 3000, "1111"), (d1, d2, 50, "1111"), bm)
    monkeypatch.setattr(ingest.pdf, "ctbc_merchant_cells", lambda data, pw: cells)
    sent = []

    def read(bms):
        sent.append(len(bms))
        return ["某某店"] * len(bms)
    monkeypatch.setattr(ingest.merchant_ocr, "read_names", read)
    return sent


def test_讀圖只送缺店名那列的格_已有店名的格不讀(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    sent = _ctbc_two_rows(monkeypatch, fake, lambda k0, k1, bm: [(k0, bm), (k1, bm)])
    ingest.run_weekly(TODAY)
    assert sent == [1]
    assert [r["c"].merchant for r in fake.rows.values()] == ["某某店", "SHOP.EXAMPLE"]


def test_讀圖_篩完沒有要補的格就不呼叫read_names(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    sent = _ctbc_two_rows(monkeypatch, fake, lambda k0, k1, bm: [(k1, bm)])      # 缺店名那列沒有對到的格
    ingest.run_weekly(TODAY)
    assert sent == []
    assert [r["c"].merchant for r in fake.rows.values()] == [None, "SHOP.EXAMPLE"]


def test_永豐網路消費通知_卡號不同不補店名(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    sp = "CardAuthService@sinopac.com"
    note = "您永豐信用卡末四碼 9999 於 2026-10-01 19:19 消費台幣10,540，商店名稱:SHOP.EXAMPLE，實際商店名稱請以帳單為準"
    _wire(monkeypatch, fake, {sp: [mail("<n>", None, note)]}, {})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    fake._add(ch(date(2026, 10, 1), 10540, card="1234"))            # 同金額同一天，但是別張卡
    ingest.run_weekly(TODAY)
    assert fake.rows[1]["c"].merchant is None


def test_清單_永豐刷卡有時間接近但金額不同的發票_照原規則分組(monkeypatch):
    fake = FakeRepo()
    fake.groups = [TxGroup("AA00000001", date(2026, 10, 1), 120, time(12, 4))]
    fake._add(replace(ch(date(2026, 10, 1), 700), charge_time="12:00"))
    _wire(monkeypatch, fake, {}, {})
    res = ingest.relist(TODAY)
    assert [(g, h) for _, g, items in res.pages for _, _, h in items] == [("other", None)]


def test_run_weekly_填LINE統計(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    _wire(monkeypatch, fake, {}, {})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    seen = []
    monkeypatch.setattr(fake, "weekly_line_stats", lambda db, since: seen.append(since) or (4, 2), raising=False)
    monkeypatch.setattr(line_repo, "listener_state", lambda db: ListenerState("kicked", None, "refresh 被拒", None))
    res = ingest.run_weekly(TODAY)
    assert (res.line_charges, res.merged, res.line_state) == (4, 2, "kicked")
    assert seen == [date(2026, 10, 11)]


def test_run_weekly_沒有listener列_line_state為None(monkeypatch):
    fake = FakeRepo()
    fake.groups = []
    _wire(monkeypatch, fake, {}, {})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    monkeypatch.setattr(fake, "weekly_line_stats", lambda db, since: (1, 0), raising=False)
    res = ingest.run_weekly(TODAY)
    assert (res.line_charges, res.merged, res.line_state) == (1, 0, None)


def test_run_weekly_讀listener狀態失敗_只警告(monkeypatch, capsys):
    fake = FakeRepo()
    fake.groups = []
    _wire(monkeypatch, fake, {}, {})
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: [], "ctbc_statement": lambda t: []})
    def boom(db): raise RuntimeError("db down")
    monkeypatch.setattr(line_repo, "listener_state", boom)
    res = ingest.run_weekly(TODAY)
    assert res.line_state is None and "⚠️" in capsys.readouterr().out
