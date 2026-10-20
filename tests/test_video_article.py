import video.extract as ext
from video.extract import article_fields, kind_of, meta_from_text


def _page(head="", body=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


# ── article_fields：標題 / 描述 ──────────────────────────────

def test_og_title_and_description_win_over_title_tag():
    html = _page(
        head='<title>網站名 - 舊標題</title>'
             '<meta property="og:title" content="唐朝的經濟">'
             '<meta property="og:description" content="安史之亂前後的財政">'
             '<meta name="description" content="一般描述">',
    )
    out = article_fields(html)
    assert out["title"] == "唐朝的經濟"
    assert out["description"] == "安史之亂前後的財政"


def test_meta_attribute_order_and_entities():
    html = _page(head='<meta content="A &amp; B &quot;史&quot;" property="og:title">')
    assert article_fields(html)["title"] == 'A & B "史"'


def test_title_tag_and_meta_description_fallback():
    html = _page(
        head='<title>  明清   的\n財政 </title><meta name="description" content="白銀流入">',
    )
    out = article_fields(html)
    assert out["title"] == "明清 的 財政"
    assert out["description"] == "白銀流入"


def test_missing_everything_gives_empty_strings():
    assert article_fields("") == {"title": "", "description": "", "text": ""}
    assert article_fields(None) == {"title": "", "description": "", "text": ""}
    assert article_fields("<html></html>") == {"title": "", "description": "", "text": ""}


# ── article_fields：內文 ──────────────────────────────────

def test_article_tag_preferred_over_main_and_p():
    html = _page(body=(
        "<p>外面的段落</p>"
        "<main><p>main 裡的段落</p>"
        "<article><h1>標題</h1><p>文章第一段。</p><p>第二段。</p></article></main>"
    ))
    text = article_fields(html)["text"]
    assert "文章第一段。" in text and "第二段。" in text
    assert "外面的段落" not in text and "main 裡的段落" not in text


def test_main_used_when_no_article():
    html = _page(body="<p>外面</p><main><div>主要內容在這</div></main>")
    assert article_fields(html)["text"] == "主要內容在這"


def test_all_paragraphs_when_no_article_or_main():
    html = _page(body="<div><p>第一段</p><span>不是段落</span><p>第二段</p></div>")
    assert article_fields(html)["text"] == "第一段 第二段"


def test_empty_article_falls_back_to_paragraphs():
    html = _page(body="<article>   </article><p>只有這段有字</p>")
    assert article_fields(html)["text"] == "只有這段有字"


def test_script_style_nav_header_footer_removed():
    html = _page(
        head="<style>.x{color:red}</style><script>var head = 'head-js';</script>",
        body=(
            "<header><p>header 文字</p></header>"
            "<nav><p>nav 文字</p></nav>"
            "<article>"
            "<script>var secret = 'script-內容';</script>"
            "<style>.y{display:none}</style>"
            "<p>正文開始</p>"
            "<footer><p>footer 文字</p></footer>"
            "</article>"
            "<footer><p>外層 footer</p></footer>"
        ),
    )
    text = article_fields(html)["text"]
    assert text == "正文開始"
    for junk in ("script", "secret", "color", "header 文字", "nav 文字", "footer 文字", "head-js"):
        assert junk not in text


def test_script_removed_in_paragraph_fallback():
    html = _page(body="<p>前<script>alert('x')</script>後</p><nav><p>導覽</p></nav>")
    text = article_fields(html)["text"]
    assert "alert" not in text and "導覽" not in text
    assert "前" in text and "後" in text


def test_entities_decoded_and_whitespace_collapsed():
    html = _page(body="<article><p>A&nbsp;&amp;&nbsp;B</p>\n\n   <p>\t&lt;史&gt;   料</p></article>")
    assert article_fields(html)["text"] == "A & B <史> 料"


def test_text_truncated_to_3000_chars():
    html = _page(body="<article><p>" + "史" * 5000 + "</p></article>")
    text = article_fields(html)["text"]
    assert len(text) == 3000
    assert set(text) == {"史"}


def test_malformed_html_does_not_raise():
    html = "<article><p>沒關的段落<div><b>粗體<p>另一段</article></body>"
    text = article_fields(html)["text"]
    assert "沒關的段落" in text and "另一段" in text


# ── kind_of ───────────────────────────────────────────────

def test_kind_of_video_platforms():
    for p in ("youtube", "instagram", "tiktok", "facebook"):
        assert kind_of(p) == "video"


def test_kind_of_everything_else_is_article():
    for p in ("other", "threads", "gmaps", "", None):
        assert kind_of(p) == "article"


# ── meta_from_text 的提示依種類 ─────────────────────────────

def _capture_prompt(monkeypatch):
    seen = {}

    def fake(prompt, schema=None):
        seen["prompt"] = prompt
        return '{"topic":"唐朝","tags":["經濟"]}'

    monkeypatch.setattr(ext, "codex_text", fake)
    return seen


def test_article_prompt_says_article(monkeypatch):
    seen = _capture_prompt(monkeypatch)
    out = meta_from_text("內文 ABC", "article")
    assert out == {"topic": "唐朝", "tags": ["經濟"]}
    assert "文章" in seen["prompt"] and "影片" not in seen["prompt"]
    assert "內文 ABC" in seen["prompt"]


def test_video_prompt_says_video_and_is_default(monkeypatch):
    seen = _capture_prompt(monkeypatch)
    meta_from_text("某支影片")
    assert "影片" in seen["prompt"] and "文章" not in seen["prompt"]
    meta_from_text("某支影片", kind="video")
    assert "影片" in seen["prompt"] and "文章" not in seen["prompt"]


def test_prompt_rules_same_for_both_kinds(monkeypatch):
    seen = _capture_prompt(monkeypatch)
    for kind in ("video", "article"):
        meta_from_text("x", kind)
        assert "單一最貼切的主題分類" in seen["prompt"]
        assert "3~5 個跨主題的關鍵字標籤" in seen["prompt"]


def test_prompt_text_with_braces_is_safe(monkeypatch):
    seen = _capture_prompt(monkeypatch)
    meta_from_text("內文有 {大括號} 和 {text}", "article")
    assert "內文有 {大括號} 和 {text}" in seen["prompt"]


# ── fetch_html：不出網，只驗守門與解碼 ─────────────────────────

class _FakeResp:
    def __init__(self, raw: bytes, charset=None):
        self._raw = raw
        self.headers = self
        self._charset = charset

    def get_content_charset(self):
        return self._charset

    def read(self, n=-1):
        return self._raw[:n] if n and n > 0 else self._raw


def test_fetch_html_refuses_unsafe_url(monkeypatch):
    monkeypatch.setattr(ext, "_is_safe_fetch_url", lambda u: False)

    def boom(*a, **k):
        raise AssertionError("不該發出請求")

    monkeypatch.setattr(ext.urllib.request, "urlopen", boom)
    assert ext.fetch_html("http://127.0.0.1:8000/x") is None


def test_fetch_html_uses_browser_ua_and_decodes_declared_charset(monkeypatch):
    monkeypatch.setattr(ext, "_is_safe_fetch_url", lambda u: True)
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        return _FakeResp("<title>歷史</title>".encode("big5"), charset="big5")

    monkeypatch.setattr(ext.urllib.request, "urlopen", fake_urlopen)
    html = ext.fetch_html("https://example.com/a")
    assert html == "<title>歷史</title>"
    assert "Mozilla/5.0" in seen["ua"] and "facebookexternalhit" not in seen["ua"]


def test_fetch_html_defaults_to_utf8_and_survives_bad_charset(monkeypatch):
    monkeypatch.setattr(ext, "_is_safe_fetch_url", lambda u: True)
    monkeypatch.setattr(ext.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp("歷史".encode("utf-8"), charset="no-such-charset"))
    assert ext.fetch_html("https://example.com/a") == "歷史"


def test_fetch_html_network_error_returns_none(monkeypatch):
    monkeypatch.setattr(ext, "_is_safe_fetch_url", lambda u: True)

    def boom(req, timeout=None):
        raise OSError("連不上")

    monkeypatch.setattr(ext.urllib.request, "urlopen", boom)
    assert ext.fetch_html("https://example.com/a") is None
