import video.ingest as ing
from tests.test_video_article import serve_by_ua
from video.extract import article_fields


def test_from_url_happy_path(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "唐朝的經濟\n某史頻道")
    monkeypatch.setattr(ing, "meta_from_text", lambda t: {"topic": "唐朝", "tags": ["經濟", "戰爭"]})
    monkeypatch.setattr(ing.repo, "add_video",
                        lambda title, url, topic=None, channel=None, platform=None:
                        ({"id": 7, "title": title, "topic": topic, "tags": []}, True))
    added = []
    monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: added.append((vid, tag)) or True)

    rec, reason = ing.from_url("https://youtu.be/x")
    assert reason == ""
    assert rec["id"] == 7 and rec["topic"] == "唐朝"
    assert rec["_created"] is True
    assert rec["tags"] == ["經濟", "戰爭"]      # 回傳前把建議標籤帶上，省一次查詢
    assert added == [(7, "經濟"), (7, "戰爭")]   # 標籤逐一入庫


def test_from_url_extract_fail_returns_reason(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    def boom(u, p):
        raise RuntimeError("yt-dlp 掛了")
    monkeypatch.setattr(ing, "_extract_from_url", boom)
    rec, reason = ing.from_url("https://youtu.be/x")
    assert rec is None and "yt-dlp 掛了" in reason


def test_from_url_no_title_falls_back_to_blob_first_line(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "  某個影片標題  \n第二行")
    monkeypatch.setattr(ing, "meta_from_text", lambda t: {"topic": "", "tags": []})
    captured = {}
    monkeypatch.setattr(ing.repo, "add_video",
                        lambda title, url, topic=None, channel=None, platform=None:
                        (captured.update(title=title, topic=topic) or {"id": 1, "tags": []}, True))
    monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: True)
    rec, reason = ing.from_url("https://youtu.be/x")
    assert reason == ""
    assert captured["title"] == "某個影片標題"   # blob 第一行當標題
    assert captured["topic"] is None             # 空 topic 不寫空字串，存 None


def test_from_url_blank_blob_returns_reason(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "")
    rec, reason = ing.from_url("https://youtu.be/x")
    assert rec is None and reason == ing._NO_TITLE_REASON


# ── 文章路徑：platform 不是 youtube／instagram／tiktok／facebook ─────────────

_ARTICLE_HTML = (
    "<html><head><title>站名 - 舊標題</title>"
    '<meta property="og:title" content="唐朝的經濟">'
    '<meta property="og:description" content="安史之亂前後的財政"></head>'
    "<body><nav><p>導覽列</p></nav>"
    "<article><p>兩稅法取代租庸調。</p><p>鹽鐵專賣支撐國庫。</p></article>"
    "<script>var ad = '廣告腳本';</script></body></html>"
)


def _stub_ai_and_repo(monkeypatch):
    """文章路徑的 AI 與入庫換成記帳用替身，並擋住 yt-dlp 那條路。回傳 (呼叫紀錄, 已入庫標籤)。"""
    calls = {"meta": [], "video": []}

    def no_ytdlp(u, p):
        raise AssertionError("文章不該走 food.extract.from_url")
    monkeypatch.setattr(ing, "_extract_from_url", no_ytdlp)

    def fake_meta(t, kind="video"):
        calls["meta"].append((t, kind))
        return {"topic": "唐朝", "tags": ["經濟", "制度"]}
    monkeypatch.setattr(ing, "meta_from_text", fake_meta)

    def fake_add(title, url, topic=None, channel=None, platform=None):
        calls["video"].append(dict(title=title, url=url, topic=topic, platform=platform))
        return {"id": 5, "title": title, "topic": topic, "tags": [], "kind": "article"}, True
    monkeypatch.setattr(ing.repo, "add_video", fake_add)
    added = []
    monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: added.append((vid, tag)) or True)
    return calls, added


def _stub_article(monkeypatch, html, *, platform="other"):
    """文章路徑的外部依賴全換掉：抓網頁（HTML 照真的解析）、AI、入庫。回傳 (呼叫紀錄, 已入庫標籤)。"""
    monkeypatch.setattr(ing, "classify_platform", lambda u: platform)
    monkeypatch.setattr(ing, "fetch_article", lambda u, p=None: article_fields(html))
    return _stub_ai_and_repo(monkeypatch)


def test_article_success_uses_og_title_and_feeds_ai_title_desc_body(monkeypatch):
    calls, added = _stub_article(monkeypatch, _ARTICLE_HTML)
    rec, reason = ing.from_url("https://example.com/tang")
    assert reason == ""
    assert rec["id"] == 5 and rec["_created"] is True and rec["tags"] == ["經濟", "制度"]
    assert calls["video"] == [dict(title="唐朝的經濟", url="https://example.com/tang",
                                   topic="唐朝", platform="other")]
    assert added == [(5, "經濟"), (5, "制度")]
    (text, kind), = calls["meta"]
    assert kind == "article"
    for piece in ("唐朝的經濟", "安史之亂前後的財政", "兩稅法取代租庸調。", "鹽鐵專賣支撐國庫。"):
        assert piece in text
    assert "導覽列" not in text and "廣告腳本" not in text


def test_article_caption_goes_first_in_ai_text(monkeypatch):
    calls, _ = _stub_article(monkeypatch, _ARTICLE_HTML)
    ing.from_url("https://example.com/tang", caption="  朋友推薦，看財政  ")
    (text, _), = calls["meta"]
    assert text.startswith("朋友推薦，看財政\n")
    assert "唐朝的經濟" in text and "兩稅法取代租庸調。" in text


def test_article_without_body_still_uses_title_and_description(monkeypatch):
    html = ('<html><head><meta property="og:title" content="只有 og">'
            '<meta property="og:description" content="只有描述"></head><body></body></html>')
    calls, _ = _stub_article(monkeypatch, html)
    rec, reason = ing.from_url("https://example.com/og-only")
    assert reason == "" and rec is not None
    assert calls["video"][0]["title"] == "只有 og"
    (text, kind), = calls["meta"]
    assert kind == "article" and text == "只有 og\n只有描述"


def test_article_title_falls_back_to_title_tag(monkeypatch):
    html = "<html><head><title>沒有 og 的文章</title></head><body><p>內文一段</p></body></html>"
    calls, _ = _stub_article(monkeypatch, html)
    rec, reason = ing.from_url("https://example.com/plain")
    assert reason == ""
    assert calls["video"][0]["title"] == "沒有 og 的文章"


def test_article_fetch_failure_returns_reason_without_saving(monkeypatch):
    calls, added = _stub_article(monkeypatch, None)
    rec, reason = ing.from_url("https://example.com/dead")
    assert rec is None and reason == ing._NO_TITLE_REASON
    assert "影片" not in reason
    assert calls["video"] == [] and calls["meta"] == [] and added == []


def test_article_without_any_title_returns_reason(monkeypatch):
    calls, _ = _stub_article(monkeypatch, "<html><body><p>有內文但沒有標題</p></body></html>")
    rec, reason = ing.from_url("https://example.com/untitled")
    assert rec is None and reason == ing._NO_TITLE_REASON
    assert calls["video"] == []


def test_article_ai_failure_does_not_block_ingest(monkeypatch):
    calls, added = _stub_article(monkeypatch, _ARTICLE_HTML)

    def boom(t, kind="video"):
        raise RuntimeError("codex 掛了")
    monkeypatch.setattr(ing, "meta_from_text", boom)
    rec, reason = ing.from_url("https://example.com/tang")
    assert reason == "" and rec["tags"] == []
    assert calls["video"][0]["topic"] is None and added == []


def test_article_unexpected_error_reported_as_extract_failure(monkeypatch):
    _stub_article(monkeypatch, _ARTICLE_HTML)
    failed = []
    monkeypatch.setattr(ing.sensors, "extract_failed", lambda *a: failed.append(a))

    def boom(u, p=None):
        raise RuntimeError("解析炸了")
    monkeypatch.setattr(ing, "fetch_article", boom)
    rec, reason = ing.from_url("https://example.com/tang")
    assert rec is None and "解析炸了" in reason
    assert len(failed) == 1 and failed[0][:2] == ("video", "other")


def test_threads_is_an_article(monkeypatch):
    calls, _ = _stub_article(monkeypatch, _ARTICLE_HTML, platform="threads")
    rec, _ = ing.from_url("https://www.threads.net/@x/post/1")
    assert calls["meta"][0][1] == "article"
    assert calls["video"][0]["platform"] == "threads"


def test_video_platforms_keep_the_ytdlp_route(monkeypatch):
    for platform in ("youtube", "instagram", "tiktok", "facebook"):
        monkeypatch.setattr(ing, "classify_platform", lambda u, p=platform: p)

        def no_fetch(u, p=None):
            raise AssertionError("影片不該走文章抓網頁")
        monkeypatch.setattr(ing, "fetch_article", no_fetch)
        seen = {}
        monkeypatch.setattr(ing, "_extract_from_url",
                            lambda u, p, seen=seen: seen.update(platform=p) or "某支影片\n頻道")
        kinds = []
        monkeypatch.setattr(ing, "meta_from_text",
                            lambda t, kind="video": kinds.append(kind) or {"topic": "", "tags": []})
        monkeypatch.setattr(ing.repo, "add_video",
                            lambda title, url, topic=None, channel=None, platform=None:
                            ({"id": 1, "title": title, "tags": []}, True))
        monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: True)
        rec, reason = ing.from_url("https://example.com/v")
        assert reason == "" and rec["title"] == "某支影片"
        assert seen["platform"] == platform and kinds == ["video"]


# ── 文章網頁的 UA：瀏覽器 UA 拿不到就換爬蟲 UA（不經 fetch_article 替身，直接換掉 urlopen）─────────

_THREADS_OG_PAGE = (
    "<html><head>"
    '<meta property="og:title" content="某作者 (@author) on Threads">'
    '<meta property="og:description" content="兩稅法其實是財政改革，不是單純加稅。">'
    "</head><body></body></html>"
)


def test_article_page_without_og_for_browser_ua_is_fetched_again_as_crawler(monkeypatch):
    calls, added = _stub_ai_and_repo(monkeypatch)
    used = serve_by_ua(monkeypatch, browser="<html><body><div>請先登入</div></body></html>",
                       crawler=_ARTICLE_HTML)
    rec, reason = ing.from_url("https://example.com/needs-crawler")
    assert reason == "" and rec is not None
    assert used == ["browser", "crawler"]
    assert calls["video"][0]["title"] == "唐朝的經濟"
    (text, kind), = calls["meta"]
    assert kind == "article" and "安史之亂前後的財政" in text and "兩稅法取代租庸調。" in text
    assert added == [(5, "經濟"), (5, "制度")]


def test_threads_link_is_fetched_with_crawler_ua_first(monkeypatch):
    calls, _ = _stub_ai_and_repo(monkeypatch)
    used = serve_by_ua(monkeypatch, browser="<html><body></body></html>", crawler=_THREADS_OG_PAGE)
    rec, reason = ing.from_url("https://www.threads.net/@author/post/ABC")
    assert reason == "" and rec is not None
    assert used == ["crawler"]
    assert calls["video"][0]["title"] == "某作者 (@author) on Threads"
    assert calls["video"][0]["platform"] == "threads"
    (text, kind), = calls["meta"]
    assert kind == "article" and "兩稅法其實是財政改革" in text


def test_article_without_title_for_either_ua_still_reports_failure(monkeypatch):
    calls, added = _stub_ai_and_repo(monkeypatch)
    used = serve_by_ua(monkeypatch, browser="<html><body><p>有字沒標題</p></body></html>", crawler=None)
    rec, reason = ing.from_url("https://example.com/untitled")
    assert rec is None and reason == ing._NO_TITLE_REASON
    assert used == ["browser", "crawler"]
    assert calls["video"] == [] and calls["meta"] == [] and added == []


def test_article_big5_page_without_header_charset_is_stored_with_readable_title(monkeypatch):
    calls, _ = _stub_ai_and_repo(monkeypatch)
    page = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=big5">'
            "<title>唐朝的經濟</title></head>"
            "<body><article><p>兩稅法取代租庸調。</p></article></body></html>").encode("big5")
    used = serve_by_ua(monkeypatch, browser=page)
    rec, reason = ing.from_url("https://example.com/big5")
    assert reason == "" and rec is not None
    assert used == ["browser"]
    assert calls["video"][0]["title"] == "唐朝的經濟"
    (text, kind), = calls["meta"]
    assert kind == "article" and "兩稅法取代租庸調。" in text
