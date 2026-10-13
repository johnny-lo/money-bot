from pathlib import Path

from mailrules import gmail_rw

SRC = Path(gmail_rw.__file__).read_text(encoding="utf-8")


def test_守衛_不讀內文_不永久刪_不寄信():
    for bad in ("BODY[]", "RFC822", "\\Deleted", "M.expunge(", "M.append(", "M.copy(", "smtplib", '"BODY.PEEK[]"'):
        assert bad not in SRC, bad
    assert "BODY.PEEK[HEADER.FIELDS" in SRC
    assert "readonly=True" in SRC


def test_utf7_往返():
    for s in ("整理/學校/abc", "整理/稅務保單", "A&B", "ascii"):
        assert gmail_rw.imap_utf7_decode(gmail_rw.imap_utf7_encode(s)) == s
    assert gmail_rw.imap_utf7_encode("A&B") == "A&-B"
    assert gmail_rw.imap_utf7_encode("整理") == "&ZXR0Bg-"


def test_解析_fetch_回應():
    meta = '12 (X-GM-MSGID 1700000000000000001 X-GM-LABELS ("\\\\Inbox" "&ZXR0Bg-/abc") UID 345 BODY[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE)] {200}'
    hdr = (b"From: =?utf-8?b?5ZWG5bqX?= <News@Shop.Example>\r\nSubject: =?utf-8?b?6YCx5bm05oW2?=\r\n"
           b"Date: Mon, 12 Oct 2026 09:00:00 +0800\r\nList-Unsubscribe: <mailto:u@x>\r\n\r\n")
    h = gmail_rw.parse_fetch(meta, hdr)
    assert (h.gm_msgid, h.uid, h.from_addr, h.subject, h.unsub, h.in_inbox) == \
        ("1700000000000000001", 345, "news@shop.example", "週年慶", True, True)
    assert "整理/abc" in h.labels and h.sent_date.isoformat() == "2026-10-12"


# ── UIDVALIDITY 守衛、登入後才有的 MOVE、壞 header 不擋同步 ──────────

import base64

import pytest

from mailrules.types import Action


class FakeM:
    """假 IMAP：記下每個寫入類指令；list/select/response/capability 照 Gmail 的形狀回。"""

    def __init__(self, uidvalidity=42, caps_at_login=(), caps_now=("IMAP4REV1", "MOVE"), msgids=None):
        self.uidvalidity, self.capabilities, self._caps_now = uidvalidity, tuple(caps_at_login), caps_now
        self.calls, self.fetch_data, self.search = [], [], b""
        self.msgids = {11: "1001", 12: "1002"} if msgids is None else msgids   # 現在 Gmail 上 uid → X-GM-MSGID

    def list(self):
        return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
                      b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"']

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def response(self, code):
        return code, [str(self.uidvalidity).encode()]

    def capability(self):
        return "OK", [" ".join(self._caps_now).encode()]

    def create(self, name):
        self.calls.append(("create", name))
        return "OK", [b""]

    def uid(self, cmd, *args):
        self.calls.append(("uid", cmd) + args)
        if cmd == "SEARCH":
            return "OK", [self.search]
        if cmd == "FETCH" and args[1] == "(X-GM-MSGID)":
            got = [int(u) for u in args[0].split(",") if int(u) in self.msgids]
            return "OK", [f"{i + 1} (UID {u} X-GM-MSGID {self.msgids[u]})".encode() for i, u in enumerate(got)] or [None]
        if cmd == "FETCH":
            return "OK", self.fetch_data
        return "OK", [b""]

    def logout(self):
        self.calls.append(("logout",))

    def writes(self):
        return [c for c in self.calls
                if c[0] == "create" or (c[0] == "uid" and c[1] in ("STORE", "MOVE"))]


ACTS = [Action("1001", 11, "label", "整理/收據"), Action("1001", 11, "archive"), Action("1002", 12, "trash")]


def test_apply_uidvalidity不符_整批中止_零寫入(monkeypatch):
    M = FakeM(uidvalidity=99)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    with pytest.raises(gmail_rw.UidValidityChanged):
        gmail_rw.apply(ACTS, expected_uidvalidity=42)
    assert M.writes() == []


def test_apply_uidvalidity相符_照常寫入(monkeypatch):
    M = FakeM(uidvalidity=42)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    done, failed, gone = gmail_rw.apply(ACTS, expected_uidvalidity=42)
    assert len(done) == 3 and failed == [] and gone == []
    assert ("create", '"' + gmail_rw.imap_utf7_encode("整理/收據") + '"') in M.calls
    assert ("uid", "STORE", "11", "+X-GM-LABELS", '("' + gmail_rw.imap_utf7_encode("整理/收據") + '")') in M.calls
    assert ("uid", "STORE", "11", "-X-GM-LABELS", "(\\Inbox)") in M.calls


def test_apply_沒有存過_uidvalidity_也不寫(monkeypatch):
    M = FakeM(uidvalidity=42)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    monkeypatch.setattr(gmail_rw, "_stored_uidvalidity", lambda: None)
    with pytest.raises(gmail_rw.UidValidityChanged):
        gmail_rw.apply(ACTS)
    assert M.writes() == []


def test_apply_預設從_mail_state_取期望值(monkeypatch):
    M = FakeM(uidvalidity=7)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    monkeypatch.setattr(gmail_rw, "_stored_uidvalidity", lambda: 8)
    with pytest.raises(gmail_rw.UidValidityChanged):
        gmail_rw.apply(ACTS)
    assert M.writes() == []


def test_trash_登入後才列出_MOVE_要用_MOVE(monkeypatch):
    M = FakeM(caps_at_login=("IMAP4REV1",), caps_now=("IMAP4REV1", "UNSELECT", "MOVE"))
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    gmail_rw.apply([Action("1002", 12, "trash")], expected_uidvalidity=42)
    assert ("uid", "MOVE", "12", '"[Gmail]/Trash"') in M.calls
    assert not any(c[:2] == ("uid", "STORE") for c in M.calls)


def test_trash_不支援_MOVE_改用_X_GM_LABELS(monkeypatch):
    M = FakeM(caps_at_login=("IMAP4REV1",), caps_now=("IMAP4REV1", "UNSELECT"))
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    gmail_rw.apply([Action("1002", 12, "trash")], expected_uidvalidity=42)
    assert ("uid", "STORE", "12", "+X-GM-LABELS", "(\\Trash)") in M.calls
    assert not any(c[:2] == ("uid", "MOVE") for c in M.calls)


def _hdr(subject_raw: bytes, frm: bytes = b"a@shop.example") -> bytes:
    return b"From: " + frm + b"\r\nSubject: " + subject_raw + b"\r\nDate: Mon, 12 Oct 2026 09:00:00 +0800\r\n\r\n"


META = '1 (X-GM-MSGID 100000000000000000{n} X-GM-LABELS () UID {n} BODY[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE)] {{50}}'


def test_header_未知_charset_不丟例外():
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr(b"=?x-no-such-charset?b?" + base64.b64encode("週年慶".encode()) + b"?="))
    assert h.from_addr == "a@shop.example" and isinstance(h.subject, str)


def test_header_壞的_big5_位元組_不丟例外():
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr(b"=?big5?b?pKT//6Q=?= tail"))
    assert h.subject.endswith("tail")


def test_header_壞的_base64_不丟例外():
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr(b"=?utf-8?b?!!!not-base64!!!?= x"))
    assert isinstance(h.subject, str)


def test_from_顯示名稱含逗號_地址不會變空():
    name = base64.b64encode(b"Shop, Inc")
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr(b"hi", b"=?utf-8?b?" + name + b"?= <News@Shop.Example>"))
    assert h.from_addr == "news@shop.example" and h.from_name == "Shop, Inc"


def test_read_headers_單封解析失敗_記錄並跳過(monkeypatch, capsys):
    M = FakeM()
    M.search = b"1 2 3"
    good = lambda n: (META.format(n=n).encode(), _hdr(b"ok"))
    M.fetch_data = [good(1), b")", (b"2 (UID 2 BODY[HEADER.FIELDS (FROM)] {5}", b"junk"), b")", good(3), b")"]
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    uidv, hs = gmail_rw.read_headers(None)
    assert uidv == 42 and [h.uid for h in hs] == [1, 3]
    assert "跳過" in capsys.readouterr().out


# ── epoch 換了以後 DB 舊列的 uid 不能拿來寫；8-bit / Big5 header 不變 U+FFFD ──

def test_apply_epoch改變後_未重讀到的舊列_零寫入(monkeypatch):
    # 新 epoch 已存進 mail_state（42 相符），但這三筆是舊 epoch 留下的 uid：
    # uid 11 現在是別封信、uid 12 現在不存在、兩封在所有郵件都搜不到 → 一封都不能動，回報已不在
    M = FakeM(uidvalidity=42, msgids={11: "5555"})
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    done, failed, gone = gmail_rw.apply(ACTS, expected_uidvalidity=42)
    assert done == [] and failed == [] and gone == ACTS
    assert M.writes() == []
    fetches = [c for c in M.calls if c[:2] == ("uid", "FETCH")]
    assert fetches and all(c[3] == "(X-GM-MSGID)" for c in fetches)


def test_apply_只寫_uid_仍對應_msgid_的動作(monkeypatch):
    M = FakeM(uidvalidity=42, msgids={11: "1001", 12: "7777"})
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    done, failed, gone = gmail_rw.apply(ACTS, expected_uidvalidity=42)
    assert done == ACTS[:2] and failed == [] and gone == ACTS[2:]
    assert not any(c[0] == "uid" and c[1] in ("STORE", "MOVE") and c[2] == "12" for c in M.calls)


def test_apply_核對_msgid_在寫入之前(monkeypatch):
    M = FakeM(uidvalidity=42)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    gmail_rw.apply(ACTS, expected_uidvalidity=42)
    first_fetch = next(i for i, c in enumerate(M.calls) if c[:2] == ("uid", "FETCH"))
    first_write = next(i for i, c in enumerate(M.calls) if c in M.writes())
    assert first_fetch < first_write


def test_header_未編碼的_8bit_utf8_主旨():
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr("週年慶 開跑".encode("utf-8")))
    assert h.subject == "週年慶 開跑"


def test_header_未編碼的_8bit_big5_主旨():
    a = gmail_rw.parse_fetch(META.format(n=1), _hdr("繳費通知".encode("cp950")))
    b = gmail_rw.parse_fetch(META.format(n=2), _hdr("出貨通知".encode("cp950")))
    assert a.subject == "繳費通知" and b.subject == "出貨通知"


def test_header_8bit_寄件者名稱():
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr(b"hi", "商店 <News@Shop.Example>".encode("utf-8")))
    assert h.from_name == "商店" and h.from_addr == "news@shop.example"


def test_header_big5_編碼字含_cp950_擴充字():
    s = "碁銹裏"                                          # 這三字 cp950 有、嚴格 big5 解不出來
    raw = b"=?big5?b?" + base64.b64encode(s.encode("cp950")) + b"?="
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr(raw))
    assert h.subject == s


def test_header_相鄰編碼字_多位元組被切開_仍正確():
    b = "週年慶".encode("utf-8")
    raw = b"=?utf-8?b?" + base64.b64encode(b[:4]) + b"?=\r\n =?utf-8?b?" + base64.b64encode(b[4:]) + b"?="
    h = gmail_rw.parse_fetch(META.format(n=1), _hdr(raw))
    assert h.subject == "週年慶"
