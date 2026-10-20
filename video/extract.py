"""連結文字 blob → {topic, tags}（codex）、文章網頁抽取，以及 YouTube 縮圖。

- kind_of：platform → "video" / "article"（youtube／instagram／tiktok／facebook 是影片，其餘是文章）
- parse_video_meta：純函式，把 codex 回應字串解析成 {topic, tags}（壞 JSON/缺欄位回空）
- meta_from_text：用 codex_text 從一段文字判主題+標籤；提示依種類寫影片或文章
- article_fields：純函式，HTML → {title, description, text}（文章專用，不動 food.extract）
- fetch_html：用一般瀏覽器 UA 抓網頁，過 food.extract 的 SSRF 守門；失敗回 None
- youtube_thumbnail：reuse food.extract.parse_video_id → 縮圖網址（非 YouTube 回 None）
"""
import json
import re
import urllib.request
from html.parser import HTMLParser

from codex_cli import codex_text
from food.extract import _is_safe_fetch_url, parse_video_id


_VIDEO_PLATFORMS = frozenset({"youtube", "instagram", "tiktok", "facebook"})


def kind_of(platform: str | None) -> str:
    """platform → "video" / "article"。沒有 platform 或不是影片平台一律算文章。"""
    return "video" if platform in _VIDEO_PLATFORMS else "article"


# kind → (量詞, 名詞, 餵進來的內容)；規則本身兩種共用。
_KIND_WORDS = {
    "video": ("一支", "影片", "標題與描述"),
    "article": ("一篇", "文章", "標題、描述與內文重點"),
}
_PROMPT = (
    "以下是{unit}歷史教學{noun}的{parts}。請判斷它的「主題」與「標籤」。\n"
    "規則：\n"
    "- topic：給單一最貼切的主題分類（例：唐朝、明清、世界大戰、台灣史），這是書架，{unit}只放一格；判斷不出回空字串。\n"
    "- tags：給 3~5 個跨主題的關鍵字標籤（例：經濟、戰爭、制度、人物），用繁體中文、不重複；判斷不出回空陣列。\n\n"
    "內容：\n"
)
# 輸出形狀交給 codex --output-schema 保證。
_VIDEO_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topic", "tags"],
    "additionalProperties": False,
}

_MAX_TAGS = 5


def parse_video_meta(raw: str) -> dict:
    """codex 回應 → {topic:str, tags:[str]}。壞 JSON / 非 dict / 缺欄位皆安全降級。"""
    try:
        d = json.loads(raw or "")
    except (ValueError, TypeError):
        return {"topic": "", "tags": []}
    if not isinstance(d, dict):
        return {"topic": "", "tags": []}
    topic = d.get("topic")
    topic = topic.strip() if isinstance(topic, str) else ""
    tags: list[str] = []
    raw_tags = d.get("tags")
    if isinstance(raw_tags, list):
        for x in raw_tags:
            s = x.strip() if isinstance(x, str) else ""
            if s and s not in tags:
                tags.append(s)
    return {"topic": topic, "tags": tags[:_MAX_TAGS]}


def _build_prompt(text: str, kind: str) -> str:
    unit, noun, parts = _KIND_WORDS.get(kind) or _KIND_WORDS["video"]
    # 內容接在 format 之後：文字裡的大括號不能被當成模板欄位
    return _PROMPT.format(unit=unit, noun=noun, parts=parts) + text


def meta_from_text(text: str, kind: str = "video") -> dict:
    """一段文字 → {topic, tags}（codex）。kind 決定提示寫影片或文章。抽不到回空。"""
    return parse_video_meta(codex_text(_build_prompt(text, kind), schema=_VIDEO_SCHEMA))


def youtube_thumbnail(url: str) -> str | None:
    """YouTube URL → hqdefault 縮圖網址；非 YouTube / 解不出回 None。"""
    vid = parse_video_id(url)
    return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if vid else None


# ── 文章網頁 ──────────────────────────────────────────────

_TITLE_MAX = 500
_DESC_MAX = 2000
_TEXT_MAX = 3000
_FETCH_MAX_BYTES = 1_000_000
_FETCH_TIMEOUT = 12
# 一般瀏覽器 UA：多數新聞／部落格站對爬蟲 UA 回精簡版或擋掉。
_BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# 不是內文的區塊：連同裡面的字整段丟掉。
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "nav", "header", "footer"})


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


class _ArticleParser(HTMLParser):
    """一趟掃完：meta／<title>，以及 <article>、<main>、<p> 三種範圍裡的可見文字。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_tag = ""
        self._in_title = False
        self._skip = 0
        self._depth = {"article": 0, "main": 0, "p": 0}
        self.chunks: dict[str, list[str]] = {"article": [], "main": [], "p": []}

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = dict(attrs)
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]
        elif tag == "title" and not self.title_tag:
            self._in_title = True
        elif tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in self._depth:
            self._depth[tag] += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in self._depth:
            self._depth[tag] = max(0, self._depth[tag] - 1)

    def handle_data(self, data):
        if self._in_title:
            self.title_tag += data
            return
        if self._skip:
            return
        for name, depth in self._depth.items():
            if depth:
                self.chunks[name].append(data)


def article_fields(html: str | None) -> dict:
    """文章 HTML → {title, description, text}，抽不到的欄位是空字串。

    - title：og:title，沒有就 <title>
    - description：og:description，沒有就 meta name=description
    - text：去掉 script／style／nav／header／footer 後，優先 <article>、其次 <main>、
      再其次所有 <p> 的可見文字；實體解碼、空白壓成單一空格、最多 3,000 字
    HTML 壞掉時用已掃到的部分，不丟例外。
    """
    parser = _ArticleParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        pass
    text = ""
    for name in ("article", "main", "p"):
        text = _squash(" ".join(parser.chunks[name]))
        if text:
            break
    title = _squash(parser.meta.get("og:title", "")) or _squash(parser.title_tag)
    desc = _squash(parser.meta.get("og:description", "")) or _squash(parser.meta.get("description", ""))
    return {"title": title[:_TITLE_MAX], "description": desc[:_DESC_MAX], "text": text[:_TEXT_MAX]}


def fetch_html(url: str) -> str | None:
    """用瀏覽器 UA 抓網頁 → HTML 字串；不安全的網址、連線或解碼失敗回 None。"""
    if not _is_safe_fetch_url(url):
        return None
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _BROWSER_UA,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        })
        r = urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT)
        raw = r.read(_FETCH_MAX_BYTES)
        charset = r.headers.get_content_charset() or "utf-8"
        try:
            return raw.decode(charset, "replace")
        except LookupError:
            return raw.decode("utf-8", "replace")
    except Exception:
        return None
