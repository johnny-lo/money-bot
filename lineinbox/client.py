"""OkLine 介面：money-line 只經過這裡碰 LINE，而且只有讀取。

okline 只在函式內 import：money-bot image 沒裝它，money-bot 與測試匯入 lineinbox 不能因此失敗。
這裡不放任何會對 LINE 寫入的呼叫（傳訊息、已讀、加好友、改設定、登出）。
"""
from collections.abc import Iterator

RECEIVE_MESSAGE = 26   # OpType：收到訊息


def load(path: str):
    """載入 session 檔；refresh 後的新 token 由 OkLine 寫回同一個檔。"""
    from okline import OkLine
    return OkLine.from_tokens_file(path, auto_refresh_schedule=True)


def close(api) -> None:
    """釋放本機資源（LTSM 的 Node 子程序、token 更新計時器），不對 LINE 發任何請求。"""
    api.close()


def find_mid(api, display_name: str) -> str:
    """displayName 完全相等的聯絡人；別的聯絡人名字可能只是包含它。0 個或多個都不猜。"""
    ids = list(api.get_all_contact_ids() or [])
    contacts = {}
    if ids:
        contacts = (api.get_contacts(ids) or {}).get("contacts") or {}
    hits = [mid for mid, c in contacts.items()
            if ((c or {}).get("contact") or {}).get("displayName") == display_name]
    if len(hits) != 1:
        raise LookupError(f"displayName 完全相等的聯絡人有 {len(hits)} 個")
    return hits[0]


def recent(api, mid: str, count: int) -> list[dict]:
    """1 對 1 聊天室最近的訊息，由舊到新（API 回新到舊）。伺服器只留約兩週，不往回翻頁。"""
    return list(reversed(api.get_recent_messages(mid, count) or []))


def messages(api) -> Iterator[dict]:
    """長連線收到的訊息；reconnect=False 讓斷線變成例外，由 listener 退避、補讀後重連。"""
    for op in api.ops.iter_operations(reconnect=False, keepalive=True):
        if op.type == RECEIVE_MESSAGE and op.message:
            yield op.message


def probe(api) -> None:
    """讀自己的 profile；session 被踢時丟 LineAuthError。"""
    api.get_profile()


def is_auth_error(exc: BaseException) -> bool:
    from okline.exceptions import LineAuthError
    return isinstance(exc, LineAuthError)
