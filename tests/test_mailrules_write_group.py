"""gmail_rw 寫入分組：核對過的動作依（種類, 標籤）分組，一個 IMAP 指令最多帶 WRITE_GROUP 個 UID；
同一批順序固定為 label → archive → trash；整組失敗（非 OK 或拋例外）退回逐封送。只用假 IMAP 與合成值。"""
import re
from dataclasses import replace

import pytest

from mailrules import gmail_rw
from mailrules.types import Action
from tests.test_mailrules_gmail import FakeM

TRASH = '"[Gmail]/Trash"'


class WriteM(FakeM):
    """記下每個 UID STORE／UID MOVE；rule(cmd, uids) 回 'OK'（預設）、'NO' 或 'boom'（拋例外）。"""

    def __init__(self, rule=None, **kw):
        super().__init__(**kw)
        self.rule = rule or (lambda cmd, uids: "OK")

    def uid(self, cmd, *args):
        if cmd in ("STORE", "MOVE"):
            self.calls.append(("uid", cmd) + args)
            verdict = self.rule(cmd, [int(u) for u in args[0].split(",")])
            if verdict == "boom":
                raise OSError("連線被重設")
            return verdict, [b""]
        return super().uid(cmd, *args)

    def cmds(self):
        return [c for c in self.calls if c[:2] in (("uid", "STORE"), ("uid", "MOVE"))]


def _setup(monkeypatch, acts, **kw):
    M = WriteM(msgids={a.uid: a.gm_msgid for a in acts}, **kw)
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    return M


def _acts(kind, uids, label=None):
    return [Action(str(1000 + u), u, kind, label) for u in uids]


def _uids(call):
    return [int(u) for u in call[2].split(",")]


def _kind(call):
    if call[1] == "MOVE" or call[3:] == ("+X-GM-LABELS", "(\\Trash)"):
        return "trash"
    return "archive" if call[3] == "-X-GM-LABELS" else "label"


def _lab(label):
    return '("' + gmail_rw.imap_utf7_encode(label) + '")'


def test_WRITE_GROUP_是_50():
    assert gmail_rw.WRITE_GROUP == 50


def test_120個同標籤的_label_送3個_STORE_50_50_20(monkeypatch):
    acts = _acts("label", range(1, 121), "整理/收據")
    M = _setup(monkeypatch, acts)
    done, failed, gone = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == [] and gone == []
    cmds = M.cmds()
    assert [len(_uids(c)) for c in cmds] == [50, 50, 20]
    assert [u for c in cmds for u in _uids(c)] == list(range(1, 121))
    assert all(c[:2] == ("uid", "STORE") and c[3:] == ("+X-GM-LABELS", _lab("整理/收據")) for c in cmds)
    assert M.calls.count(("create", '"' + gmail_rw.imap_utf7_encode("整理/收據") + '"')) == 1


def test_不同標籤分開送(monkeypatch):
    acts = _acts("label", [1, 2], "整理/收據") + _acts("label", [3], "整理/學校") + _acts("label", [4], "整理/收據")
    M = _setup(monkeypatch, acts)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []
    assert [(c[2], c[4]) for c in M.cmds()] == [("1,2,4", _lab("整理/收據")), ("3", _lab("整理/學校"))]


def test_archive_分組_移出收件匣(monkeypatch):
    acts = _acts("archive", range(1, 61))
    M = _setup(monkeypatch, acts)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []
    assert [len(_uids(c)) for c in M.cmds()] == [50, 10]
    assert all(c[:2] == ("uid", "STORE") and c[3:] == ("-X-GM-LABELS", "(\\Inbox)") for c in M.cmds())


def test_trash_有_MOVE_用_UID_MOVE_分組(monkeypatch):
    acts = _acts("trash", range(1, 52))
    M = _setup(monkeypatch, acts)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []
    assert [len(_uids(c)) for c in M.cmds()] == [50, 1]
    assert all(c[:2] == ("uid", "MOVE") and c[3:] == (TRASH,) for c in M.cmds())


def test_trash_沒有_MOVE_用_X_GM_LABELS_Trash_分組(monkeypatch):
    acts = _acts("trash", range(1, 4))
    M = _setup(monkeypatch, acts, caps_now=("IMAP4REV1",))
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []
    assert [(c[1], c[2], c[3:]) for c in M.cmds()] == [("STORE", "1,2,3", ("+X-GM-LABELS", "(\\Trash)"))]


def test_順序固定_所有_label_再_archive_再_trash_同一封信先標籤後移出或丟掉(monkeypatch):
    acts = (_acts("trash", [1]) + _acts("archive", [2]) + _acts("label", [1, 2], "整理/收據")
            + _acts("trash", [3]) + _acts("label", [3], "整理/學校"))
    M = _setup(monkeypatch, acts)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []
    cmds = M.cmds()
    assert [_kind(c) for c in cmds] == ["label", "label", "archive", "trash"]
    for uid in (1, 3):
        i_label = next(i for i, c in enumerate(cmds) if _kind(c) == "label" and uid in _uids(c))
        i_trash = next(i for i, c in enumerate(cmds) if _kind(c) == "trash" and uid in _uids(c))
        assert i_label < i_trash
    i_label2 = next(i for i, c in enumerate(cmds) if _kind(c) == "label" and 2 in _uids(c))
    i_arch = next(i for i, c in enumerate(cmds) if _kind(c) == "archive" and 2 in _uids(c))
    assert i_label2 < i_arch


def test_done_與_failed_維持輸入順序(monkeypatch):
    acts = (_acts("trash", [1]) + _acts("label", [2], "整理/收據") + _acts("archive", [3])
            + _acts("label", [4], "整理/學校") + _acts("label", [5], "整理/收據"))
    _setup(monkeypatch, acts)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []


def test_整組_NO_逐封重送_只有那封進_failed(monkeypatch):
    acts = _acts("label", [1, 2, 3, 4], "整理/收據")
    rule = lambda cmd, uids: "NO" if len(uids) > 1 or uids == [3] else "OK"
    M = _setup(monkeypatch, acts, rule=rule)
    done, failed, gone = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == [acts[0], acts[1], acts[3]] and failed == [acts[2]] and gone == []
    assert [c[2] for c in M.cmds()] == ["1,2,3,4", "1", "2", "3", "4"]
    assert all(c[3:] == ("+X-GM-LABELS", _lab("整理/收據")) for c in M.cmds())


def test_整組拋例外_逐封全_OK_全部進_done(monkeypatch):
    acts = _acts("archive", [1, 2, 3])
    rule = lambda cmd, uids: "boom" if len(uids) > 1 else "OK"
    M = _setup(monkeypatch, acts, rule=rule)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []
    assert [c[2] for c in M.cmds()] == ["1,2,3", "1", "2", "3"]


def test_逐封時拋例外的那封算_failed_其餘照送(monkeypatch):
    acts = _acts("trash", [1, 2, 3])
    rule = lambda cmd, uids: "NO" if len(uids) > 1 else ("boom" if uids == [2] else "OK")
    M = _setup(monkeypatch, acts, rule=rule)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == [acts[0], acts[2]] and failed == [acts[1]]
    assert [c[2] for c in M.cmds()] == ["1,2,3", "1", "2", "3"]


def test_整組_OK_不逐封重送(monkeypatch):
    acts = _acts("label", [1, 2, 3], "整理/收據")
    M = _setup(monkeypatch, acts)
    gmail_rw.apply(acts, expected_uidvalidity=42)
    assert [c[2] for c in M.cmds()] == ["1,2,3"]


def test_一組失敗不影響其他組(monkeypatch):
    acts = _acts("label", [1, 2], "整理/收據") + _acts("label", [3, 4], "整理/學校") + _acts("trash", [5, 6])
    rule = lambda cmd, uids: "NO" if uids in ([1, 2], [1], [2]) else "OK"
    M = _setup(monkeypatch, acts, rule=rule)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert failed == acts[:2] and done == acts[2:]
    assert ("uid", "MOVE", "5,6", TRASH) in M.calls


def test_換過_uid_的動作_用新_uid_分組寫入_done_帶新_uid(monkeypatch):
    M = WriteM(msgids={1: "1001", 30: "1002"})
    M.search = b"30"
    acts = [Action("1002", 2, "label", "整理/收據"), Action("1001", 1, "label", "整理/收據")]
    monkeypatch.setattr(gmail_rw, "_connect", lambda: M)
    done, failed, gone = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert failed == [] and gone == [] and done == [acts[1], replace(acts[0], uid=30)]
    assert [c[2] for c in M.cmds()] == ["1,30"]


def test_未知種類算_failed_不送任何指令(monkeypatch):
    acts = [Action("1001", 1, "expunge")]
    M = _setup(monkeypatch, acts)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == [] and failed == acts and M.cmds() == []


def test_寫入種類仍只有_CREATE_STORE_MOVE(monkeypatch):
    acts = (_acts("label", range(1, 4), "整理/收據") + _acts("archive", range(1, 4)) + _acts("trash", range(1, 4)))
    M = _setup(monkeypatch, acts)
    gmail_rw.apply(acts, expected_uidvalidity=42)
    assert {c[1] for c in M.calls if c[0] == "uid"} <= {"FETCH", "SEARCH", "STORE", "MOVE"}
    assert {c[0] for c in M.calls} <= {"select", "create", "uid", "logout"}
    src = open(gmail_rw.__file__, encoding="utf-8").read()
    assert set(re.findall(r'"(STORE|MOVE|COPY|EXPUNGE|APPEND)"', src)) <= {"STORE", "MOVE"}


def test_每批寫入前仍先核對_跨_CHUNK_各批各自分組(monkeypatch):
    acts = _acts("label", range(1, 7), "整理/收據")
    M = _setup(monkeypatch, acts)
    monkeypatch.setattr(gmail_rw, "CHUNK", 4)
    done, failed, _ = gmail_rw.apply(acts, expected_uidvalidity=42)
    assert done == acts and failed == []
    assert [c[2] for c in M.cmds()] == ["1,2,3,4", "5,6"]
    i_fetch2 = [i for i, c in enumerate(M.calls) if c[:2] == ("uid", "FETCH")][1]
    i_write1 = next(i for i, c in enumerate(M.calls) if c in M.cmds())
    assert i_write1 < i_fetch2
