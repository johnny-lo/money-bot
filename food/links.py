"""URL 偵測 + 平台判斷(純函式,無 I/O,可單測)。"""
import re
from urllib.parse import urlsplit

# 比對 http(s) URL,容許大部分 URL 合法字元(RFC 3986 子集)
_URL_RE = re.compile(r'https?://[^\s<>"　，。！？、）)】」』]+', re.IGNORECASE)
# 句尾標點(中英文,半全形)要剝掉
_TRAILING = '.,;:!?。，、！？)】」』 　'

# 平台 → 認可的網域(子網域邊界比對,防釣魚)
_HOST_RULES = {
    "youtube":   ["youtube.com", "youtu.be"],
    "instagram": ["instagram.com", "instagr.am"],
    "threads":   ["threads.com", "threads.net"],
    "tiktok":    ["tiktok.com"],
    "facebook":  ["facebook.com", "fb.com", "fb.watch", "m.facebook.com"],
    "gmaps":     ["google.com/maps", "maps.app.goo.gl", "goo.gl/maps", "maps.google.com"],
}


def find_urls(text: str) -> list[str]:
    """從文字抽出所有 http(s) URL,保序去重、剝句尾標點。"""
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(_TRAILING)
        if url and url not in seen:
            seen[url] = None
    return list(seen.keys())


def classify_platform(url: str) -> str:
    """判斷 URL 屬於哪個平台。host 用子網域邊界比對防釣魚。"""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = (parts.path or "")
    except Exception:
        return "other"
    if not host:
        return "other"
    # gmaps 需要 host+path 一起看(google.com/maps、goo.gl/maps)
    full = host + path
    for plat, hosts in _HOST_RULES.items():
        for h in hosts:
            if "/" in h:
                # 含路徑:整段比對(host+path 開頭)
                if full.startswith(h) or full.startswith("www." + h):
                    return plat
            else:
                # 純 host:邊界比對(完全相等或子網域)
                if host == h or host.endswith("." + h):
                    return plat
    return "other"


def strip_urls(text: str) -> str:
    """移除文字中的 URL,留下使用者註解。"""
    if not text:
        return ""
    return _URL_RE.sub("", text).strip(" \t\n") if _URL_RE.sub("", text).strip() else ""


def detect_links(text: str) -> list[dict]:
    """偵測所有連結 → list of {platform, url}。"""
    return [{"platform": classify_platform(u), "url": u} for u in find_urls(text)]


def first_link(text: str) -> dict | None:
    """取第一個連結,沒有回 None。"""
    links = detect_links(text)
    return links[0] if links else None
