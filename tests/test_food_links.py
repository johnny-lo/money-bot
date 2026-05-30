from food.links import find_urls, classify_platform, strip_urls, detect_links, first_link


def test_find_urls_basic():
    assert find_urls("吃這家 https://www.instagram.com/reel/ABC/ 很讚") == ["https://www.instagram.com/reel/ABC/"]


def test_find_urls_multiple_dedup_preserve_order():
    txt = "https://youtu.be/x https://www.instagram.com/p/Y/ https://youtu.be/x"
    assert find_urls(txt) == ["https://youtu.be/x", "https://www.instagram.com/p/Y/"]


def test_find_urls_strips_chinese_punctuation():
    # 句尾全形句號 / 半形句點 / 全形右括號要剝掉
    assert find_urls("看這個 https://www.tiktok.com/@x/video/123。") == ["https://www.tiktok.com/@x/video/123"]
    assert find_urls("(來源 https://example.com/abc)") == ["https://example.com/abc"]


def test_find_urls_discord_angle_brackets():
    # Discord <url> 抑制預覽格式,要正確抓中間 URL
    assert find_urls("<https://www.youtube.com/watch?v=ABC>") == ["https://www.youtube.com/watch?v=ABC"]


def test_find_urls_empty():
    assert find_urls("") == []
    assert find_urls("沒有連結的文字") == []


def test_classify_platform_youtube():
    assert classify_platform("https://www.youtube.com/watch?v=ABC") == "youtube"
    assert classify_platform("https://youtu.be/ABC") == "youtube"
    assert classify_platform("https://www.youtube.com/shorts/XYZ") == "youtube"


def test_classify_platform_instagram():
    assert classify_platform("https://www.instagram.com/reel/ABC/") == "instagram"
    assert classify_platform("https://www.instagram.com/p/XYZ/") == "instagram"


def test_classify_platform_threads():
    assert classify_platform("https://www.threads.com/@x/post/ABC") == "threads"
    assert classify_platform("https://www.threads.net/@x/post/ABC") == "threads"


def test_classify_platform_tiktok():
    assert classify_platform("https://www.tiktok.com/@x/video/123") == "tiktok"
    assert classify_platform("https://vt.tiktok.com/abc/") == "tiktok"


def test_classify_platform_facebook():
    assert classify_platform("https://www.facebook.com/foo/posts/123") == "facebook"
    assert classify_platform("https://fb.watch/abc/") == "facebook"


def test_classify_platform_gmaps():
    assert classify_platform("https://www.google.com/maps/place/鼎泰豐") == "gmaps"
    assert classify_platform("https://maps.app.goo.gl/abc") == "gmaps"
    assert classify_platform("https://goo.gl/maps/abc") == "gmaps"


def test_classify_platform_phishing_subdomain():
    # 子網域邊界比對:youtube.com.evil.com 應判 other
    assert classify_platform("https://youtube.com.evil.com/abc") == "other"


def test_classify_platform_other():
    assert classify_platform("https://example.com/abc") == "other"


def test_strip_urls():
    assert strip_urls("吃這家 https://x.com 很讚") == "吃這家  很讚"
    assert strip_urls("https://x.com") == ""
    assert strip_urls("沒連結") == "沒連結"


def test_detect_links_returns_dicts():
    out = detect_links("看 https://www.youtube.com/watch?v=A 和 https://www.instagram.com/p/B/")
    assert out == [
        {"platform": "youtube", "url": "https://www.youtube.com/watch?v=A"},
        {"platform": "instagram", "url": "https://www.instagram.com/p/B/"},
    ]


def test_first_link_none_when_no_url():
    assert first_link("純文字") is None


def test_first_link_returns_first():
    assert first_link("https://youtu.be/A https://www.tiktok.com/@x/video/1") == {
        "platform": "youtube", "url": "https://youtu.be/A",
    }
