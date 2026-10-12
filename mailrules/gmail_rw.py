"""Gmail IMAP：只讀信頭、只做三種寫入（建標籤、±X-GM-LABELS、丟垃圾桶）。

硬規矩（守衛測試掃原始碼）：不讀內文、不永久刪、不寄信；讀取一律 readonly=True；
IMAP 連線變數一律叫 M。寫入時用的 UID SEARCH X-GM-MSGID 只拿來查信現在的 uid（唯讀）。
"""
import base64
import email
import email.quoprimime
import email.utils
import imaplib
import os
import re
from dataclasses import replace

from app_secrets import get_secret

from .types import Action, MailHeader

HOST = "imap.gmail.com"
FIELDS = "(FROM SUBJECT DATE LIST-UNSUBSCRIBE)"
FETCH_ITEMS = f"(X-GM-MSGID X-GM-LABELS BODY.PEEK[HEADER.FIELDS {FIELDS}])"
CHUNK = 500

imaplib.Commands.setdefault("MOVE", ("SELECTED",))     # 舊版 imaplib 的 uid() 不認得 MOVE


# ── modified UTF-7（RFC 3501 §5.1.3） ───────────────────────────────

def imap_utf7_encode(s: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            b64 = base64.b64encode("".join(buf).encode("utf-16-be")).decode("ascii")
            out.append("&" + b64.rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def imap_utf7_decode(s: str) -> str:
    def dec(m):
        if m.group(1) == "":
            return "&"
        b64 = m.group(1).replace(",", "/")
        b64 += "=" * (-len(b64) % 4)
        return base64.b64decode(b64).decode("utf-16-be")
    return re.sub(r"&([^-]*)-", dec, s)


# ── 解析 ───────────────────────────────────────────────────────────

class UidValidityChanged(RuntimeError):
    """Gmail 的 UIDVALIDITY 跟 mail_state 存的不同：DB 裡的 UID 已指向別封信，整批不寫。"""


_BIG5 = {"big5", "big-5", "x-big5", "cp950", "big5hkscs", "big5-hkscs", "ms950"}
_EW = re.compile(r"=\?([^?\s]+)\?([bBqQ])\?([^?\s]*)\?=")


def _bytes_text(b: bytes, charset: str | None = None) -> str:
    """位元組 → 字串：宣告 big5 先試 cp950／big5hkscs（擴充字）；沒宣告依序試 utf-8、cp950、big5hkscs；最後才 replace。"""
    cs = (charset or "").lower()
    if cs in _BIG5:
        tries = ["cp950", "big5hkscs"]
    elif cs:
        tries = [cs]
    else:
        tries = ["utf-8", "cp950", "big5hkscs"]
    for t in tries:
        try:
            return b.decode(t)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return b.decode(tries[0], "replace")
    except LookupError:                                    # 未知 charset
        return _bytes_text(b)


def _undo_8bit(s: str) -> str:
    """email 套件把未編碼的 8-bit 位元組存成 surrogateescape；取回原始位元組重新猜編碼。"""
    if not any("\udc80" <= ch <= "\udcff" for ch in s):
        return s
    return _bytes_text(s.encode("utf-8", "surrogateescape"))


def _decode(s: str | None) -> str:
    """RFC 2047 解碼。相鄰同 charset 的編碼字先接位元組再解（多位元組字會被切開）；
    壞 header（未知 charset、壞 base64、壞 Big5）退回 replace 或原字串，絕不丟例外。"""
    s = s or ""
    parts: list[list] = []                                 # [charset 或 None, bytes 或 str]
    pos = 0
    for m in _EW.finditer(s):
        gap = s[pos:m.start()]
        pos = m.end()
        if gap and not (gap.isspace() and parts and parts[-1][0] is not None):
            parts.append([None, gap])                      # 兩個編碼字之間的空白要丟掉
        cs, enc, txt = m.group(1).split("*")[0].lower(), m.group(2).lower(), m.group(3)
        try:
            if enc == "b":
                raw = base64.b64decode(txt + "=" * (-len(txt) % 4), validate=True)
            else:
                raw = email.quoprimime.header_decode(txt).encode("latin-1")
        except Exception:
            parts.append([None, m.group(0)])
            continue
        if parts and parts[-1][0] == cs:
            parts[-1][1] += raw
        else:
            parts.append([cs, raw])
    if s[pos:]:
        parts.append([None, s[pos:]])
    return "".join(x if cs is None else _bytes_text(x, cs) for cs, x in parts)


def _raw(hdr, name: str) -> str:
    """原始 header 值（不經 compat32 的 unknown-8bit 處理，那會把 8-bit 位元組變 U+FFFD）。"""
    for k, v in hdr.raw_items():
        if k.lower() == name.lower():
            return _undo_8bit(str(v))
    return ""


def _labels(meta: str) -> list[str]:
    m = re.search(r'X-GM-LABELS \(((?:"(?:[^"\\]|\\.)*"|[^()"])*)\)', meta)
    if not m:
        return []
    out = []
    for quoted, atom in re.findall(r'"((?:[^"\\]|\\.)*)"|([^\s()"]+)', m.group(1)):
        raw = re.sub(r"\\(.)", r"\1", quoted) if not atom else atom
        out.append(imap_utf7_decode(raw))
    return out


def parse_fetch(meta: str, header_bytes: bytes) -> MailHeader:
    gid = re.search(r"X-GM-MSGID (\d+)", meta).group(1)
    uid = int(re.search(r"\bUID (\d+)", meta).group(1))
    labels = _labels(meta)
    hdr = email.message_from_bytes(header_bytes)
    name, addr = email.utils.parseaddr(_raw(hdr, "From"))     # 先拆原始 header，再只解碼名稱（解碼後的逗號會讓 parseaddr 失靈）
    name = _decode(name)
    try:
        sent = email.utils.parsedate_to_datetime(hdr["Date"]).date()
    except Exception:
        sent = None
    return MailHeader(gm_msgid=gid, uid=uid, from_addr=addr.lower(), from_name=name,
                      subject=" ".join(_decode(_raw(hdr, "Subject")).split()), sent_date=sent,
                      labels=tuple(labels), unsub=hdr["List-Unsubscribe"] is not None,
                      in_inbox=any(x.lower() == "\\inbox" for x in labels))


# ── 連線 ───────────────────────────────────────────────────────────

def _connect():
    addr = (os.getenv("GMAIL_ADDRESS") or "").strip()
    pw = get_secret("GMAIL_APP_PASSWORD")
    if not addr or not pw:
        raise RuntimeError("缺 GMAIL_ADDRESS 環境變數或 gmail_app_password secret")
    M = imaplib.IMAP4_SSL(HOST)
    M.login(addr, pw.replace(" ", ""))
    return M


_ALL, _TRASH = b"\\All", b"\\Trash"


def _special(M, flag: bytes) -> str:
    for f in M.list()[1]:
        if f and flag in f:
            return re.search(r'"([^"]+)"$', f.decode()).group(1)
    raise RuntimeError(f"找不到 Gmail 資料夾 {flag.decode()}")


def _logout(M) -> None:
    try:
        M.logout()
    except Exception:
        pass


def _parse_into(out: list, pending) -> None:
    """單封解析失敗只記錄並跳過，不讓一封壞信卡死整個同步。"""
    if not pending:
        return
    try:
        out.append(parse_fetch(*pending))
    except Exception as e:
        print(f"⚠️ mailrules 跳過一封無法解析的信頭：{type(e).__name__}: {e} ({pending[0][:60]!r})")


def read_headers(since_uid: int | None) -> tuple[int, list[MailHeader]]:
    M = _connect()
    try:
        all_mail = _special(M, _ALL)
        M.select('"' + all_mail + '"', readonly=True)
        uidv = int(M.response("UIDVALIDITY")[1][0])
        crit = "ALL" if since_uid is None else f"UID {since_uid + 1}:*"
        uids = [int(u) for u in (M.uid("SEARCH", crit)[1][0] or b"").split()]
        if since_uid is not None:
            uids = [u for u in uids if u > since_uid]     # `n:*` 沒新信時會回傳最後一封
        out: list[MailHeader] = []
        for i in range(0, len(uids), CHUNK):
            seq = ",".join(map(str, uids[i:i + CHUNK]))
            typ, data = M.uid("FETCH", seq, FETCH_ITEMS)
            if typ != "OK":
                raise RuntimeError(f"FETCH 失敗：{typ}")
            pending = None                                 # [meta, header_bytes]
            for item in data:
                if isinstance(item, tuple):
                    _parse_into(out, pending)
                    pending = [item[0].decode("utf-8", "replace"), item[1]]
                elif isinstance(item, bytes) and pending:
                    pending[0] += " " + item.decode("utf-8", "replace")   # literal 後面的尾巴（標籤可能在這）
            _parse_into(out, pending)
        return uidv, out
    finally:
        _logout(M)


# ── 寫入（只有三種） ───────────────────────────────────────────────

def _stored_uidvalidity() -> int | None:
    """mail_state 存的 UIDVALIDITY（DB 裡的 UID 是在這個值底下抓的）。"""
    from database import session_scope
    from . import repo
    with session_scope() as db:
        state = repo.get_state(db)
    return None if state is None else state[0]


def _has_move(M) -> bool:
    """imaplib 登入後不會更新 M.capabilities，而 Gmail 登入後才列出 MOVE → 要重新問一次。"""
    try:
        typ, data = M.capability()
        if typ == "OK":
            return b"MOVE" in b" ".join(d for d in data if isinstance(d, bytes)).upper().split()
    except Exception:
        pass
    return False


def _current_msgids(M, uids: list[int]) -> dict[int, str]:
    """唯讀核對：這些 UID 現在各是哪封信（只抓 X-GM-MSGID，不碰內文也不改旗標）。"""
    typ, data = M.uid("FETCH", ",".join(map(str, uids)), "(X-GM-MSGID)")
    if typ != "OK":
        return {}
    out = {}
    for item in data:
        line = item[0] if isinstance(item, tuple) else item
        if not isinstance(line, bytes):
            continue
        line = line.decode("utf-8", "replace")
        u, g = re.search(r"\bUID (\d+)", line), re.search(r"X-GM-MSGID (\d+)", line)
        if u and g:
            out[int(u.group(1))] = g.group(1)
    return out


def _find_uids(M, gm_msgids: set[str]) -> dict[str, int]:
    """唯讀查詢：用 X-GM-MSGID 在所有郵件找這封信現在的 UID；找不到（已刪、在垃圾桶）就不列。"""
    out = {}
    for g in sorted(gm_msgids):
        typ, data = M.uid("SEARCH", "X-GM-MSGID", str(g))
        if typ != "OK":
            raise RuntimeError(f"SEARCH 失敗：{typ}")
        uids = [int(u) for u in (data[0] or b"").split()] if data else []
        if uids:
            out[g] = uids[0]
    return out


def _verify(M, batch: list[Action]) -> tuple[list[Action], list[Action], list[Action]]:
    """寫入前核對：uid 仍對應 gm_msgid 的直接寫；對不上的用 X-GM-MSGID 找新 uid、再核對一次。
    回傳 (ok, failed, gone)；ok 裡換過 uid 的動作帶新 uid。"""
    current = _current_msgids(M, sorted({a.uid for a in batch}))
    ok = [a for a in batch if current.get(a.uid) == str(a.gm_msgid)]
    lost = [a for a in batch if current.get(a.uid) != str(a.gm_msgid)]
    if not lost:
        return ok, [], []
    found = _find_uids(M, {str(a.gm_msgid) for a in lost})
    recheck = _current_msgids(M, sorted(set(found.values()))) if found else {}
    failed, gone = [], []
    for a in lost:
        u = found.get(str(a.gm_msgid))
        if u is None:
            gone.append(a)
        elif recheck.get(u) == str(a.gm_msgid):
            ok.append(replace(a, uid=u))
        else:
            failed.append(a)
    return ok, failed, gone


def apply(actions: list[Action], expected_uidvalidity: int | None = None
          ) -> tuple[list[Action], list[Action], list[Action]]:
    """寫入前先核對 UIDVALIDITY；不符（或沒存過）→ UidValidityChanged，一封都不寫。
    每批寫入前再唯讀核對 UID → X-GM-MSGID；uid 對不上的先用 X-GM-MSGID 在所有郵件找新 uid
    （找到再核對一次才寫，找不到 → gone）。某一批核對或寫入拋例外（例如斷線）→ 那一批整批進 failed，
    已完成的批次照常回傳。回傳 (done, failed, gone)；done 裡的 uid 是實際寫入的 uid。"""
    if not actions:
        return [], [], []
    done, failed, gone = [], [], []
    M = _connect()
    try:
        trash = _special(M, _TRASH)
        use_move = _has_move(M)
        typ, _ = M.select('"' + _special(M, _ALL) + '"')
        if typ != "OK":
            raise RuntimeError(f"SELECT 失敗：{typ}")
        expected = _stored_uidvalidity() if expected_uidvalidity is None else expected_uidvalidity
        actual = int(M.response("UIDVALIDITY")[1][0])
        if expected is None or actual != expected:
            raise UidValidityChanged(f"UIDVALIDITY 變了（DB {expected}、Gmail {actual}），{len(actions)} 筆都沒寫")
        created: set[str] = set()
        for i in range(0, len(actions), CHUNK):
            batch = actions[i:i + CHUNK]
            b_done, b_failed = [], []
            try:
                ok, b_failed, b_gone = _verify(M, batch)
                for label in sorted({a.label for a in ok if a.kind == "label" and a.label} - created):
                    created.add(label)
                    try:
                        M.create('"' + imap_utf7_encode(label) + '"')
                    except Exception:
                        pass                               # 已存在
                _write(M, ok, trash, use_move, b_done, b_failed)
            except Exception as e:
                print(f"⚠️ mailrules 第 {i // CHUNK + 1} 批寫入中斷，整批 {len(batch)} 筆算失敗：{type(e).__name__}: {e}")
                failed += batch
                continue
            done += b_done
            failed += b_failed
            gone += b_gone
    finally:
        _logout(M)
    return done, failed, gone


def _write(M, actions: list[Action], trash: str, use_move: bool, done: list, failed: list) -> None:
    for a in actions:
        try:
            if a.kind == "label":
                typ, _ = M.uid("STORE", str(a.uid), "+X-GM-LABELS", '("' + imap_utf7_encode(a.label) + '")')
            elif a.kind == "archive":
                typ, _ = M.uid("STORE", str(a.uid), "-X-GM-LABELS", "(\\Inbox)")
            elif a.kind == "trash":
                if use_move:
                    typ, _ = M.uid("MOVE", str(a.uid), '"' + trash + '"')
                else:
                    typ, _ = M.uid("STORE", str(a.uid), "+X-GM-LABELS", "(\\Trash)")
            else:
                typ = "NO"
        except Exception:
            typ = "NO"
        (done if typ == "OK" else failed).append(a)
