from datetime import date

from cardrecon import ingest
from cardrecon.types import Charge, RawMail, Receipt, TxGroup, TxHint

TODAY = date(2026, 10, 18)


def ch(d, amount, n=0, src="sinopac_daily"):
    return Charge(source=src, card_last4="1234", charge_date=d, amount=amount, line_no=n)


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
    def set_merchant(self, db, m): self.merchants = m
    def used_group_keys(self, db): return set()
    def load_groups(self, db, since): return self.groups
    def mark_matched(self, db, m):
        for i, k in m.items():
            self.rows[i].update(status="matched", key=k)
    hint_txs = ()
    def load_hints(self, db, since): return list(self.hint_txs)
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


def _wire(monkeypatch, fake, mails, texts):
    monkeypatch.setattr(ingest, "repo", fake)
    monkeypatch.setattr(ingest, "get_secret", lambda k: "A123456789")
    monkeypatch.setattr(ingest.gmail, "fetch", lambda sender, kw, since=None: mails.get(sender, []))
    monkeypatch.setattr(ingest.pdf, "extract_text", lambda data, pw: texts.get(data))


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
    monkeypatch.setattr(ingest.parse, "parse_autopass", lambda t: Receipt(date(2026, 10, 1), 110, "停車費"))
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
    fake.hint_txs = [TxHint("t1", date(2026, 10, 2), 1040, "某店")]
    _wire(monkeypatch, fake, {"spendservice@sinopac.com": [mail("<a>", b"A")]}, {b"A": "a"})
    monkeypatch.setattr(ingest.config, "PAGE_SIZE", 2)
    charges = [ch(date(2026, 10, 2), 1000, 0), ch(date(2026, 10, 2), 50, 1), ch(date(2026, 10, 2), 60, 2),
               ch(date(2026, 10, 2), 70, 3), ch(date(2026, 10, 2), 500, 4)]
    monkeypatch.setattr(ingest.parse, "PARSERS", {"sinopac_daily": lambda t: charges, "ctbc_statement": lambda t: []})
    res = ingest.run_weekly(TODAY)
    assert [(b, g, [i for i, _, _ in items]) for b, g, items in res.pages] == [
        ("2026-10-18-1", "near", [1]), ("2026-10-18-2", "small", [2, 3]),
        ("2026-10-18-3", "small", [4]), ("2026-10-18-4", "other", [5])]
    assert res.pages[0][2][0][2].startswith("≈ 帳上 10/02 某店")
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
