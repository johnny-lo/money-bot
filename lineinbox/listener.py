"""money-line 的主程式：補讀 → 長連線收新訊息 → 心跳；被踢就等人重新登入。

    python -m lineinbox.listener             # 容器的 CMD
    python -m lineinbox.listener --dry-run   # 只讀、只分類、印筆數，不寫 DB

只處理被監看 mid 傳來的訊息，其他聊天室的訊息在記憶體裡直接丟掉。
任何輸出都不含訊息文字；錯誤只記例外類別名（例外訊息可能夾帶訊息內容）。
被踢或找不到聊天室時不重試登入、不結束程序（restart 會變成一直撞登入），
改成盯 session 檔的 mtime，本人重新掃碼寫入新 session 後自己接著收。
"""
import argparse
import os
import sys
import threading
import time
from collections import Counter

from . import client, process
from . import repo as inbox_repo
from .config import (BACKOFF_MAX, BACKOFF_START, HEARTBEAT_SEC, KICKED_POLL_SEC, RECENT_COUNT,
                     SESSION_PATH, WATCHED)
from .types import ERROR, KICKED, OK, STARTING

_state_lock = threading.Lock()
_current_state: str | None = None


def next_delay(failures: int) -> float:
    return min(BACKOFF_START * 2 ** failures, BACKOFF_MAX)


def _log(text: str) -> None:
    print(f"[line] {text}", flush=True)


def _session():
    from database import session_scope
    return session_scope()


def _ensure_tables() -> None:
    """money-line 可能比 money-bot 先起來：自己建這兩張表（create_all 對已存在的表不做事）。"""
    from database import Base, engine
    from models import LineListenerState, LineMessage
    Base.metadata.create_all(engine, tables=[LineMessage.__table__, LineListenerState.__table__])


def _set_state(state: str, error: str | None = None) -> None:
    """跟心跳 thread 共用一把鎖：避免心跳在被踢之後把狀態蓋回 OK。DB 寫失敗只記類別名，不讓 listener 掛掉。"""
    global _current_state
    with _state_lock:
        _current_state = state
        try:
            with _session() as db:
                inbox_repo.set_state(db, state, error)
        except Exception as e:
            _log(f"⚠️ 寫入狀態 {state} 失敗：{type(e).__name__}")


def _heartbeat_loop() -> None:
    while True:
        time.sleep(HEARTBEAT_SEC)
        with _state_lock:
            if _current_state != OK:
                continue
            try:
                with _session() as db:
                    inbox_repo.set_state(db, OK)
            except Exception as e:
                _log(f"⚠️ 心跳寫入失敗：{type(e).__name__}")


def _mtime(path: str) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _wait_session_change(path: str, stamp: float | None) -> None:
    """每 KICKED_POLL_SEC 看一次 session 檔；存在且 mtime 跟 stamp 不同才回。"""
    while True:
        time.sleep(KICKED_POLL_SEC)
        now = _mtime(path)
        if now is not None and now != stamp:
            return


def _watched_mids(api) -> dict[str, str]:
    """被監看帳號的 mid → 來源鍵。1 對 1 聊天室的 message box id 就是對方的 mid。"""
    return {client.find_mid(api, name): source for name, source in WATCHED.items()}


def _handle(msg: dict, source: str) -> str | None:
    with _session() as db:
        return process.handle(db, msg, source)


def _summary(counts: Counter) -> str:
    return " ".join(f"{k}={n}" for k, n in sorted(counts.items())) or "-"


def _catch_up(api, mids: dict[str, str]) -> None:
    """伺服器還留著的最近訊息逐則冪等處理；不往回翻頁（get_previous_messages 只回 end message 本身）。"""
    done = Counter()
    for mid, source in mids.items():
        for msg in client.recent(api, mid, RECENT_COUNT):
            if msg.get("from") != mid:
                continue
            status = _handle(msg, source)
            if status is not None:
                done[status] += 1
    _log(f"補讀完成：新處理 {sum(done.values())} 則（{_summary(done)}）")


def _is_kicked(api, exc: Exception) -> bool:
    if client.is_auth_error(exc):
        return True
    try:
        client.probe(api)
    except Exception as e:
        return client.is_auth_error(e)
    return False


def _serve(api, mids: dict[str, str]) -> None:
    """補讀＋長連線，斷線就退避、補讀後重連；只有被踢才回。"""
    failures = 0
    while True:
        try:
            _catch_up(api, mids)
            _set_state(OK)
            for msg in client.messages(api):
                failures = 0
                source = mids.get(msg.get("from"))
                if source is None:
                    continue
                status = _handle(msg, source)
                if status is not None:
                    _log(f"新訊息：{status}")
            raise ConnectionError("長連線結束")
        except Exception as e:
            if _is_kicked(api, e):
                _set_state(KICKED, type(e).__name__)
                _log(f"⚠️ 被 LINE 踢掉（{type(e).__name__}），等重新登入")
                return
            delay = next_delay(failures)
            _set_state(ERROR, type(e).__name__)
            _log(f"⚠️ {type(e).__name__}，{delay:g} 秒後補讀再重連")
            time.sleep(delay)
            failures += 1


def _run(path: str) -> None:
    _ensure_tables()
    _set_state(STARTING)
    threading.Thread(target=_heartbeat_loop, name="line-heartbeat", daemon=True).start()
    failures = 0
    while True:
        api = None
        try:
            api = client.load(path)
            mids = _watched_mids(api)
        except Exception as e:
            if api is not None:
                client.close(api)
            if isinstance(e, LookupError):
                _set_state(ERROR, "找不到聊天室")
                _log("⚠️ 找不到聊天室，等 session 檔換新")
            elif isinstance(e, FileNotFoundError) or client.is_auth_error(e):
                # 不能用 OSError：requests 的連線錯誤也是 OSError，那種要退避重試
                _set_state(KICKED, type(e).__name__)
                _log(f"⚠️ session 無法使用（{type(e).__name__}），等重新登入")
            else:
                delay = next_delay(failures)
                _set_state(ERROR, type(e).__name__)
                _log(f"⚠️ 連線失敗：{type(e).__name__}，{delay:g} 秒後再試")
                time.sleep(delay)
                failures += 1
                continue
            _wait_session_change(path, _mtime(path))
            continue
        failures = 0
        _log(f"已連線，監看 {len(mids)} 個聊天室")
        _serve(api, mids)
        client.close(api)
        _wait_session_change(path, _mtime(path))
        _log("session 檔已更新，重新載入")


def _dry_run(path: str) -> int:
    """只讀、只分類：不寫 DB、不開長連線，只印各 kind／狀態的筆數。"""
    api = None
    try:
        api = client.load(path)
        mids = _watched_mids(api)
        kinds, statuses = Counter(), Counter()
        for mid, source in mids.items():
            for msg in client.recent(api, mid, RECENT_COUNT):
                if msg.get("from") != mid:
                    continue
                m, status, _ = process.classify(msg, source)
                kinds[m.kind] += 1
                statuses[status] += 1
    except Exception as e:
        _log(f"⚠️ dry-run 失敗：{type(e).__name__}")
        return 1
    finally:
        if api is not None:
            client.close(api)
    _log(f"dry-run：{sum(kinds.values())} 則")
    _log(f"kind {_summary(kinds)}")
    _log(f"status {_summary(statuses)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lineinbox.listener")
    parser.add_argument("--dry-run", action="store_true", help="只讀、只分類、印筆數，不寫 DB")
    parser.add_argument("--session", default=SESSION_PATH, help="OkLine session 檔")
    args = parser.parse_args(argv)
    if args.dry_run:
        return _dry_run(args.session)
    _run(args.session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
