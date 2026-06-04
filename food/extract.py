"""影片/文字/截圖 → 店家欄位 JSON。

- parse_extracted_json：純函式，把 AI 回應字串解析成 {name, area, recommended_items, cuisine_type}
- from_text：用 codex_text 把純文字抽成欄位
- from_image：用 gemini_image 直接從截圖一步到位抽欄位
"""
import json
import urllib.request
import urllib.parse

from gemini import gemini_image
from codex_cli import codex_text


def _strip_markdown_fence(t: str) -> str:
    """去掉 AI 回應可能包覆的 markdown code fence（```json … ```）。"""
    t = (t or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


_TEXT_PROMPT = (
    "請從以下文字內容中擷取店家資訊，只回 JSON、不要 markdown 標籤：\n"
    '{{"name":"店名(沒有就空字串)","area":"區域提示(縣市/城市)","'
    'recommended_items":"文中明確稱讚/必點/招牌的具體菜名(例:歐巴豬五花、招牌牛肉麵);沒明確推薦就空字串,不要放料理類別","'
    'cuisine_type":"店家主要販售的料理類型(例:拉麵、咖啡、早午餐、火鍋);可空"}}\n\n'
    "注意:recommended_items 必須是文中明確被稱讚/必點的具體菜名(例:鼎泰豐的「小籠包」);\n"
    "若文中只列出店家賣的料理類別(如「拉麵、咖啡、早午餐」)而沒明確推薦,留空字串,\n"
    "那些料理類別填進 cuisine_type 即可。\n\n"
    "文字內容：\n{text}"
)

_IMAGE_PROMPT = (
    "請從這張圖片擷取店家資訊，只回 JSON、不要 markdown 標籤：\n"
    '{"name":"店名(沒有就空字串)","area":"區域提示(縣市/城市)","'
    'recommended_items":"圖中明確稱讚/必點/招牌的具體菜名(例:歐巴豬五花、招牌牛肉麵);沒明確推薦就空字串,不要放料理類別","'
    'cuisine_type":"店家主要販售的料理類型(例:拉麵、咖啡、早午餐、火鍋);可空"}\n\n'
    "注意:recommended_items 必須是圖中明確被稱讚/必點的具體菜名(例:鼎泰豐的「小籠包」);\n"
    "若圖中只列出店家賣的料理類別(如「拉麵、咖啡、早午餐」)而沒明確推薦,留空字串,\n"
    "那些料理類別填進 cuisine_type 即可。"
)


def parse_extracted_json(raw: str) -> dict:
    """把 AI 回應字串清成乾淨 dict。缺欄位以空字串補齊、首尾空白皆 strip。"""
    d = json.loads(_strip_markdown_fence(raw))
    return {
        "name": (d.get("name") or "").strip(),
        "area": (d.get("area") or "").strip(),
        "recommended_items": (d.get("recommended_items") or "").strip(),
        "cuisine_type": (d.get("cuisine_type") or "").strip(),
    }


def from_text(text: str) -> dict:
    """純文字 → 欄位（codex）。"""
    return parse_extracted_json(codex_text(_TEXT_PROMPT.format(text=text)))


def from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """截圖 → 欄位（Gemini Vision 一次到位）。"""
    return parse_extracted_json(gemini_image(_IMAGE_PROMPT, image_bytes, mime_type=mime_type))


import re as _re

_YT_ID_RE = _re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|v/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def parse_video_id(url: str) -> str | None:
    """從 YouTube URL 解出 11 碼 video id;非 YouTube 或解不出回 None。"""
    if not url:
        return None
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


from urllib.parse import unquote_plus as _unquote_plus

_GMAPS_PLACE_RE = _re.compile(r"/maps/place/([^/@?]+)")


def gmaps_place_name(url: str) -> str:
    """從 Google Maps URL 解出店名;解不出回空字串。"""
    if not url:
        return ""
    m = _GMAPS_PLACE_RE.search(url)
    if not m:
        return ""
    return _unquote_plus(m.group(1)).strip()


import html as _html

_OG_RE_TITLE = _re.compile(
    r'<meta[^>]+(?:'
    r'property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']'
    r'|content=["\']([^"\']*)["\'][^>]+property=["\']og:title["\']'
    r')',
    _re.IGNORECASE,
)
_OG_RE_DESC = _re.compile(
    r'<meta[^>]+(?:'
    r'property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']'
    r'|content=["\']([^"\']*)["\'][^>]+property=["\']og:description["\']'
    r')',
    _re.IGNORECASE,
)
_OG_MAX = 2000


def _og_first(html_body: str, regex) -> str:
    m = regex.search(html_body or "")
    if not m:
        return ""
    raw = next((g for g in m.groups() if g), "")
    return _html.unescape(raw)[:_OG_MAX]


def parse_og(html_body: str) -> dict:
    """從 HTML body 抽 og:title 與 og:description;沒有回空字串。"""
    return {
        "title": _og_first(html_body, _OG_RE_TITLE),
        "description": _og_first(html_body, _OG_RE_DESC),
    }


_FETCH_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"  # Meta 平台對爬蟲 UA 才回 og meta;一般網站也接受。實測 Threads 用瀏覽器 UA 拿不到、用 facebookexternalhit 拿得到 og:description
_FETCH_TIMEOUT = 12
_FETCH_MAX_BYTES = 400_000


def _yt_dlp_blob(url: str) -> str | None:
    """用 yt-dlp 抽 title + description。失敗回 None。"""
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True}) as y:
            info = y.extract_info(url, download=False)
        title = (info.get("title") or "").strip()
        desc = (info.get("description") or "").strip()
        uploader = (info.get("uploader") or "").strip()
        parts = [p for p in (title, uploader, desc) if p]
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def _http_get(url: str) -> tuple[str, str] | None:
    """fetch URL → (final_url, body)。失敗回 None。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _FETCH_UA,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        })
        r = urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT)
        body = r.read(_FETCH_MAX_BYTES).decode("utf-8", "ignore")
        return r.geturl(), body
    except Exception:
        return None


def from_url(url: str, platform: str) -> str | None:
    """從連結抽『要餵 codex 的文字 blob』。失敗回 None 代表降級。

    - youtube / instagram / tiktok / facebook → 先試 yt-dlp,失敗退 og fetch
    - threads → og fetch(yt-dlp 不支援,但爬蟲 UA 拿得到 og:description)
    - gmaps → follow redirect → gmaps_place_name
    - other → og:title + og:description
    """
    if not url:
        return None

    if platform == "gmaps":
        got = _http_get(url)
        if not got:
            return None
        final_url, _ = got
        name = gmaps_place_name(final_url) or gmaps_place_name(url)
        return name or None

    # 主力:yt-dlp(YouTube/IG/TikTok/FB 的 caption 通常最完整)
    if platform in ("youtube", "instagram", "tiktok", "facebook"):
        blob = _yt_dlp_blob(url)
        if blob:
            return blob
        # 退到 og fetch(yt-dlp 失敗時)

    # og fetch(Threads / FB/IG/TikTok 退路 / 一般網站)
    got = _http_get(url)
    if not got:
        return None
    _, body = got
    og = parse_og(body)
    parts = [og.get("title", ""), og.get("description", "")]
    blob = "\n".join(p for p in parts if p)
    return blob or None


import json as _json
import subprocess as _subprocess
import tempfile as _tempfile

_DEEP_TIMEOUT = 120  # 上限
_DEEP_PROMPT = """任務:從這個美食社群連結抽出店家資訊。
連結: {url}
{hint_line}
請用任何方式取得內容並判斷(curl/python/yt-dlp/看圖辨識招牌/Google 搜尋交叉驗證)。
特別注意:店名常常在影片畫面/招牌圖片裡,文字描述可能只有地區/心得。

請只回 JSON,不要其他文字、不要 markdown 標籤:
{{"name":"店名","area":"地區/縣市","recommended_items":"內容中明確稱讚/必點/招牌的具體菜名(例:歐巴豬五花、招牌牛肉麵);沒明確推薦就空字串,不要放料理類別","cuisine_type":"店家主要販售的料理類型(例:拉麵、咖啡、早午餐、火鍋)"}}

重要區分:
- recommended_items 必須是內容中明確被稱讚/必點的具體菜名(例:鼎泰豐的「小籠包」);
  若只列出店家賣的料理類別(如「拉麵、咖啡、早午餐」)而沒明確推薦,留空字串,
  那些料理類別填進 cuisine_type 即可。
- 任一欄位真的拿不到就空字串。整個都拿不到回所有欄位空字串的 JSON。"""


def deep_extract_via_codex(url: str, *, hint: str = "") -> dict | None:
    """注意:這是 blocking subprocess(120s timeout);從 async 路徑呼叫請用 asyncio.to_thread 包(Task 8 已正確包了)。

    codex full-access 看圖 + 搜尋深度振查。失敗回 None。"""
    if not url:
        return None
    hint_line = f"使用者額外提示: {hint}\n" if hint.strip() else ""
    prompt = _DEEP_PROMPT.format(url=url, hint_line=hint_line)
    fd, out_path = _tempfile.mkstemp(suffix=".json")
    import os as _os
    _os.close(fd)
    try:
        cmd = [
            "codex", "exec",
            "--ephemeral", "--skip-git-repo-check",
            "-s", "danger-full-access",
            "-C", "/tmp",
            "-o", out_path,
            "-",
        ]
        proc = _subprocess.run(
            cmd, input=prompt, text=True,
            capture_output=True, timeout=_DEEP_TIMEOUT,
        )
        if proc.returncode != 0:
            return None
        with open(out_path, encoding="utf-8") as f:
            raw = f.read()
        data = _json.loads(_strip_markdown_fence(raw))
        return {
            "name": (data.get("name") or "").strip(),
            "area": (data.get("area") or "").strip(),
            "recommended_items": (data.get("recommended_items") or "").strip(),
            "cuisine_type": (data.get("cuisine_type") or "").strip(),
        }
    except Exception:
        return None
    finally:
        try:
            _os.remove(out_path)
        except OSError:
            pass


_PLACE_LIST_PROMPT = (
    "以下每行是一家店（已去掉清單勾選框）。請逐行擷取店家資訊，"
    "回一個 JSON 陣列、長度等於行數、順序對齊每一行，只回 JSON、不要 markdown 標籤：\n"
    '[{{"name":"店名(該行抽不到就空字串)","area":"區域提示(縣市/城市/分店);沒有就空字串",'
    '"recommended_items":"該行明確稱讚/必點的具體菜名;沒有就空字串,不要放料理類別",'
    '"cuisine_type":"料理類型(例:拉麵、咖啡、火鍋);可空"}}]\n\n'
    "注意:\n"
    "- 每行尾端可能有括號(可能沒收尾,例如「映客 (台中」),括號內若是地區/分店填 area、"
    "若是推薦菜填 recommended_items、若是純感想則忽略。\n"
    "- 陣列長度必須等於下方行數,第 i 個物件對應第 i 行;某行抽不出店名就回 name 空字串。\n"
    "- recommended_items 必須是明確被稱讚/必點的具體菜名;只列料理類別就留空、填進 cuisine_type。\n\n"
    "店家清單(每行一家)：\n{lines}"
)


def _empty_fields() -> dict[str, str]:
    return {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}


def parse_place_list_json(raw: str, n: int) -> list[dict]:
    """把 codex 回的 JSON 陣列字串清成『對齊 n 行』的 list[fields]（純函式，可單測）。

    - 去 markdown 包覆；每欄 strip、缺欄位補空字串。
    - 陣列短於 n → 補空 name；長於 n → 截到 n。
    - 整段 JSON 壞掉/非 list → 回 n 筆全空（落 ❌，不假裝成功）。
    """
    t = _strip_markdown_fence(raw)
    try:
        data = json.loads(t)
    except Exception:
        data = None
    if not isinstance(data, list):
        return [_empty_fields() for _ in range(n)]
    out: list[dict] = []
    for d in data[:n]:
        if not isinstance(d, dict):
            out.append(_empty_fields())
            continue
        out.append({
            "name": (d.get("name") or "").strip(),
            "area": (d.get("area") or "").strip(),
            "recommended_items": (d.get("recommended_items") or "").strip(),
            "cuisine_type": (d.get("cuisine_type") or "").strip(),
        })
    while len(out) < n:
        out.append(_empty_fields())
    return out


def parse_place_list(lines: list[str]) -> list[dict]:
    """一次 codex 批解析整份清單 → 對齊行序的 list[fields]。I/O 邊界,不單測。

    lines 為已去掉清單勾選框前綴的店名內容（呼叫端負責先剝除前綴）。
    codex_text 走 stdin、可承載超長 batch；回的陣列由 parse_place_list_json 對齊行數。
    """
    n = len(lines)
    if n == 0:
        return []
    blob = "\n".join(lines)
    raw = codex_text(_PLACE_LIST_PROMPT.format(lines=blob))
    return parse_place_list_json(raw, n)
