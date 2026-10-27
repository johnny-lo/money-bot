import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from cardrecon import repo as card_repo
from lineinbox import client, listener, process
from lineinbox import repo as inbox_repo


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "ctbc_line"
MID = "U00000000000000000000000000000000"        # fixture 的 from
OTHER_MID = "U22222222222222222222222222222222"
OTHER_TEXT = "別的聊天室的悄悄話"


def _fixtures() -> list[dict]:
    names = ("store", "online", "foreign_usd", "foreign_twd", "deposit")
    return [json.loads((FIXTURES / f"{n}.json").read_text()) for n in names]


def _other_chat() -> dict:
    return {"id": "900000000000000099", "from": OTHER_MID, "to": MID, "toType": 0,
            "createdTime": 1788608580000, "contentType": 0, "text": OTHER_TEXT, "contentMetadata": {}}


def _ids(msgs):
    return [m["id"] for m in msgs]


# ── next_delay ─────────────────────────────────────────────

def test_next_delay():
    assert listener.next_delay(0) == 5
    assert listener.next_delay(1) == 10
    assert listener.next_delay(7) == 600
    assert listener.next_delay(50) == 600


# ── client：只有讀取 ───────────────────────────────────────

def test_client_只有讀取():
    src = (ROOT / "lineinbox" / "client.py").read_text()
    for word in ("send_", "mark_read", "react", "unsend", "add_friend", "logout", "set_", "broadcast", ".reply("):
        assert word not in src, word


def test_client_不在模組層import_okline():
    src = (ROOT / "lineinbox" / "client.py").read_text()
    top = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    assert not any("okline" in ln for ln in top)


class FakeContactsApi:
    def __init__(self, names: dict[str, str]):
        self.names = names

    def get_all_contact_ids(self):
        return list(self.names)

    def get_contacts(self, mids):
        return {"contacts": {m: {"contact": {"displayName": self.names[m]}} for m in mids}}


def test_find_mid_完全相等才算():
    api = FakeContactsApi({"U1": "中國信託小幫手", "U2": "中國信託", "U3": "王小明"})
    assert client.find_mid(api, "中國信託") == "U2"


def test_find_mid_只是包含_不算():
    api = FakeContactsApi({"U1": "中國信託小幫手", "U3": "我的中國信託"})
    with pytest.raises(LookupError):
        client.find_mid(api, "中國信託")


def test_find_mid_找到兩個_丟LookupError():
    api = FakeContactsApi({"U1": "中國信託", "U2": "中國信託"})
    with pytest.raises(LookupError):
        client.find_mid(api, "中國信託")


def test_find_mid_沒有聯絡人_丟LookupError():
    with pytest.raises(LookupError):
        client.find_mid(FakeContactsApi({}), "中國信託")


class FakeOp:
    def __init__(self, type_, message):
        self.type, self.message = type_, message


class FakeOpsApi:
    def __init__(self, ops):
        self.calls, self._ops = [], ops
        self.ops = self

    def iter_operations(self, **kw):
        self.calls.append(kw)
        return iter(self._ops)


def test_messages_只取收到訊息的operation():
    msg = {"id": "1", "from": MID}
    api = FakeOpsApi([FakeOp(25, {"id": "0"}), FakeOp(26, msg), FakeOp(26, None), FakeOp(48, None)])
    assert list(client.messages(api)) == [msg]
    assert api.calls == [{"reconnect": False, "keepalive": True}]


def test_recent_由舊到新():
    class Api:
        def get_recent_messages(self, mid, count):
            assert (mid, count) == (MID, 200)
            return [{"id": "3"}, {"id": "2"}, {"id": "1"}]
    assert _ids(client.recent(Api(), MID, 200)) == ["1", "2", "3"]


def test_recent_伺服器回None_當成空():
    class Api:
        def get_recent_messages(self, mid, count):
            return None
    assert client.recent(Api(), MID, 200) == []


# ── listener：不寫、不洩漏 ──────────────────────────────────

@pytest.fixture
def no_writes(monkeypatch):
    """任何 DB 寫入或開 session 都記下來；dry-run 必須一次都沒有。"""
    hits = []

    def bomb(name):
        def _f(*a, **k):
            hits.append(name)
            raise AssertionError(f"不該呼叫 {name}")
        return _f

    for name in ("exists", "save_message", "set_status", "set_state", "mark_alerted"):
        monkeypatch.setattr(inbox_repo, name, bomb(f"lineinbox.repo.{name}"))
    monkeypatch.setattr(card_repo, "upsert_charges", bomb("cardrecon.repo.upsert_charges"))
    monkeypatch.setattr(listener, "_session", bomb("listener._session"))
    monkeypatch.setattr(listener, "_ensure_tables", bomb("listener._ensure_tables"))
    return hits


def _fake_client(monkeypatch, recent_msgs, *, stream=None):
    api = object()
    monkeypatch.setattr(client, "load", lambda path: api)
    monkeypatch.setattr(client, "close", lambda a: None)

    def find_mid(a, name):
        if name == "中國信託":
            return MID
        raise LookupError(name)
    monkeypatch.setattr(client, "find_mid", find_mid)
    monkeypatch.setattr(client, "recent", lambda a, mid, count: [m for m in recent_msgs] if mid == MID else [])

    def messages(a):
        if stream is None:
            raise AssertionError("dry-run 不該開長連線")
        return stream()
    monkeypatch.setattr(client, "messages", messages)
    return api


def test_dry_run_只印筆數_不印訊息文字_不寫DB(monkeypatch, capsys, no_writes):
    _fake_client(monkeypatch, [*_fixtures(), _other_chat()])

    assert listener.main(["--dry-run"]) == 0

    out = capsys.readouterr()
    text = out.out + out.err
    assert no_writes == []
    assert "parsed=2" in text and "non_twd=2" in text and "other=1" in text
    assert "spend=4" in text
    for leaked in ("XX炸雞", "ＸＸ炸雞", "NT$1,280", "NT$359", "1234", "刷卡通知", "入帳", OTHER_TEXT, MID, OTHER_MID):
        assert leaked not in text, leaked


def test_dry_run_找不到聊天室_回非0且不寫(monkeypatch, capsys, no_writes):
    _fake_client(monkeypatch, _fixtures())
    monkeypatch.setattr(client, "find_mid", lambda a, name: (_ for _ in ()).throw(LookupError(name)))
    assert listener.main(["--dry-run"]) != 0
    assert no_writes == []


# ── listener：串流、斷線、被踢 ─────────────────────────────

class AuthErr(Exception):
    pass


@pytest.fixture
def serve_env(monkeypatch):
    """_serve 的外部依賴全換掉：DB session、狀態寫入、handle、sleep、auth 判斷。"""
    env = {"states": [], "handled": [], "sleeps": [], "probe_error": None, "now": 1000.0}

    @contextmanager
    def session():
        yield "db"
    monkeypatch.setattr(listener, "_session", session)
    monkeypatch.setattr(inbox_repo, "set_state",
                        lambda db, state, error=None, now=None: env["states"].append((state, error)))

    def handle(db, msg, source):
        env["handled"].append((msg["id"], source))
        return "parsed"
    monkeypatch.setattr(process, "handle", handle)
    monkeypatch.setattr(listener.time, "sleep", lambda s: env["sleeps"].append(s))
    monkeypatch.setattr(listener.time, "monotonic", lambda: env["now"])   # 時鐘只在測試推進時才動
    monkeypatch.setattr(client, "is_auth_error", lambda e: isinstance(e, AuthErr))

    def probe(api):
        if env["probe_error"]:
            raise env["probe_error"]
    monkeypatch.setattr(client, "probe", probe)
    return env


def test_serve_只處理被監看mid_斷線退避後先補讀_被踢就停(monkeypatch, capsys, serve_env):
    store, deposit = _fixtures()[0], _fixtures()[4]
    rounds = iter([
        [_other_chat(), deposit, RuntimeError("XX炸雞 NT$1,280")],
        [AuthErr("kicked")],
    ])

    def stream():
        for item in next(rounds):
            if isinstance(item, Exception):
                raise item
            yield item
    api = _fake_client(monkeypatch, [store], stream=stream)

    listener._serve(api, {MID: "ctbc"})

    assert serve_env["handled"] == [
        ("900000000000000001", "ctbc"),   # 補讀
        ("900000000000000005", "ctbc"),   # 長連線；別的聊天室那則直接丟掉
        ("900000000000000001", "ctbc"),   # 斷線後重連前先補讀
    ]
    assert serve_env["states"] == [("ok", None), ("error", "RuntimeError"), ("ok", None), ("kicked", "AuthErr")]
    assert serve_env["sleeps"] == [5]
    out = capsys.readouterr()
    for leaked in ("XX炸雞", "NT$1,280", OTHER_TEXT):
        assert leaked not in out.out + out.err


def test_serve_連續失敗_退避加倍(monkeypatch, serve_env):
    rounds = iter([[ConnectionError()], [ConnectionError()], [AuthErr()]])

    def stream():
        for item in next(rounds):
            raise item
        yield  # pragma: no cover
    api = _fake_client(monkeypatch, [], stream=stream)

    listener._serve(api, {MID: "ctbc"})

    assert serve_env["sleeps"] == [5, 10]
    assert serve_env["states"][-1] == ("kicked", "AuthErr")


def _rounds_stream(serve_env, rounds):
    """每輪是一串動作：dict ＝ 收到訊息、數字 ＝ 時鐘往前推幾秒、例外 ＝ 連線中斷。"""
    rounds = iter(rounds)

    def stream():
        for item in next(rounds):
            if isinstance(item, Exception):
                raise item
            if isinstance(item, (int, float)):
                serve_env["now"] += item
                continue
            yield item
    return stream


def test_serve_連線撐過穩定秒數才斷_退避歸零(monkeypatch, serve_env):
    stream = _rounds_stream(serve_env, [[60, ConnectionError()], [60, ConnectionError()], [AuthErr()]])
    api = _fake_client(monkeypatch, [], stream=stream)

    listener._serve(api, {MID: "ctbc"})

    assert serve_env["sleeps"] == [5, 5]
    assert serve_env["states"][-1] == ("kicked", "AuthErr")


def test_serve_連線馬上就斷_退避加倍(monkeypatch, serve_env):
    stream = _rounds_stream(serve_env, [[ConnectionError()], [ConnectionError()], [AuthErr()]])
    api = _fake_client(monkeypatch, [], stream=stream)

    listener._serve(api, {MID: "ctbc"})

    assert serve_env["sleeps"] == [5, 10]


def test_serve_連線沒撐到穩定秒數_不歸零(monkeypatch, serve_env):
    stream = _rounds_stream(serve_env, [[59, ConnectionError()], [59, ConnectionError()], [AuthErr()]])
    api = _fake_client(monkeypatch, [], stream=stream)

    listener._serve(api, {MID: "ctbc"})

    assert serve_env["sleeps"] == [5, 10]


def test_serve_只有被監看的訊息才讓退避歸零(monkeypatch, serve_env):
    deposit = _fixtures()[4]
    stream = _rounds_stream(serve_env, [
        [ConnectionError()],
        [_other_chat(), ConnectionError()],     # 別的聊天室的訊息不算連線恢復
        [deposit, ConnectionError()],
        [AuthErr()],
    ])
    api = _fake_client(monkeypatch, [], stream=stream)

    listener._serve(api, {MID: "ctbc"})

    assert serve_env["sleeps"] == [5, 10, 5]


def test_serve_一般例外但probe被踢_當成被踢不退避(monkeypatch, serve_env):
    serve_env["probe_error"] = AuthErr()

    def stream():
        raise ConnectionError()
        yield  # pragma: no cover
    api = _fake_client(monkeypatch, [], stream=stream)

    listener._serve(api, {MID: "ctbc"})

    assert serve_env["sleeps"] == []
    assert serve_env["states"] == [("ok", None), ("kicked", "ConnectionError")]


def test_wait_session_change_mtime變了才回(monkeypatch, tmp_path):
    path = tmp_path / "tokens.json"
    stamps = iter([None, 100.0, 100.0, None, 200.0])
    monkeypatch.setattr(listener, "_mtime", lambda p: next(stamps))
    sleeps = []
    monkeypatch.setattr(listener.time, "sleep", lambda s: sleeps.append(s))

    listener._wait_session_change(str(path), 100.0)

    assert sleeps == [60] * 5     # 先等再看；檔案不見或 mtime 沒變都繼續等


class _Stop(Exception):
    pass


@pytest.fixture
def run_env(monkeypatch, serve_env):
    """_run 是無限迴圈：等 session 檔換新那一步丟 _Stop 跳出來。"""
    env = dict(serve_env, waits=0, loads=0, load_errors=[])
    monkeypatch.setattr(listener, "_ensure_tables", lambda: None)
    monkeypatch.setattr(listener.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())

    def wait(path, stamp):
        env["waits"] += 1
        raise _Stop()
    monkeypatch.setattr(listener, "_wait_session_change", wait)

    def load(path):
        env["loads"] += 1
        if env["load_errors"]:
            raise env["load_errors"].pop(0)
        return object()
    monkeypatch.setattr(client, "load", load)
    monkeypatch.setattr(client, "close", lambda a: None)
    return env


def test_run_找不到聊天室_記錯誤並等session檔_不重試(monkeypatch, run_env):
    monkeypatch.setattr(client, "find_mid", lambda a, name: (_ for _ in ()).throw(LookupError(name)))
    with pytest.raises(_Stop):
        listener._run("/nowhere/tokens.json")
    assert run_env["states"] == [("starting", None), ("error", "找不到聊天室")]
    assert (run_env["loads"], run_env["waits"], run_env["sleeps"]) == (1, 1, [])


def test_run_連線錯誤_退避重試_不當成被踢(monkeypatch, run_env):
    run_env["load_errors"] = [ConnectionError(), FileNotFoundError()]
    with pytest.raises(_Stop):
        listener._run("/nowhere/tokens.json")
    assert run_env["states"] == [("starting", None), ("error", "ConnectionError"), ("kicked", "FileNotFoundError")]
    assert run_env["sleeps"] == [5] and run_env["waits"] == 1
