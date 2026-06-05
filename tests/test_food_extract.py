from food.extract import parse_extracted_json


def test_parse_plain_json():
    raw = '{"name":"鼎泰豐","area":"信義","recommended_items":"小籠包","cuisine_type":"中式"}'
    out = parse_extracted_json(raw)
    assert out == {"name": "鼎泰豐", "area": "信義",
                   "recommended_items": "小籠包", "cuisine_type": "中式"}


def test_parse_with_markdown_fences():
    raw = "```json\n{\"name\":\"A\",\"area\":\"\",\"recommended_items\":\"\",\"cuisine_type\":\"\"}\n```"
    out = parse_extracted_json(raw)
    assert out["name"] == "A"
    assert out["area"] == ""


def test_parse_missing_fields_defaults_empty():
    raw = '{"name":"B"}'
    out = parse_extracted_json(raw)
    assert out == {"name": "B", "area": "", "recommended_items": "", "cuisine_type": ""}


def test_parse_whitespace_stripped():
    raw = '   {"name":"  C  ","area":" 台北 "}  '
    out = parse_extracted_json(raw)
    assert out["name"] == "C"
    assert out["area"] == "台北"


from food.extract import parse_video_id


def test_parse_video_id_watch():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_video_id_youtu_be():
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ?si=xxx") == "dQw4w9WgXcQ"


def test_parse_video_id_shorts():
    assert parse_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_video_id_embed():
    assert parse_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_video_id_with_extra_params():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s") == "dQw4w9WgXcQ"


def test_parse_video_id_not_youtube():
    assert parse_video_id("https://example.com/abc") is None
    assert parse_video_id("https://www.instagram.com/reel/ABC/") is None


from food.extract import gmaps_place_name


def test_gmaps_chinese_place():
    url = "https://www.google.com/maps/place/鼎泰豐+信義店/@25.033,121.530,17z/data=!3m1"
    assert gmaps_place_name(url) == "鼎泰豐 信義店"


def test_gmaps_url_encoded():
    url = "https://www.google.com/maps/place/%E9%BC%8E%E6%B3%B0%E8%B1%90/@25,121,15z"
    assert gmaps_place_name(url) == "鼎泰豐"


def test_gmaps_english():
    url = "https://www.google.com/maps/place/Din+Tai+Fung/@25,121,15z"
    assert gmaps_place_name(url) == "Din Tai Fung"


def test_gmaps_coords_only():
    # 沒有 /place/<name>/ 段(只有座標)應回空字串
    assert gmaps_place_name("https://www.google.com/maps/@25.033,121.530,17z") == ""


def test_gmaps_not_maps_url():
    assert gmaps_place_name("https://example.com/abc") == ""


from food.extract import parse_og


def test_parse_og_basic():
    html = '<meta property="og:title" content="某店家 - 美食媒體"><meta property="og:description" content="台北信義區">'
    assert parse_og(html) == {"title": "某店家 - 美食媒體", "description": "台北信義區"}


def test_parse_og_attribute_order_swapped():
    # content 在前、property 在後
    html = '<meta content="X" property="og:title">'
    assert parse_og(html)["title"] == "X"


def test_parse_og_html_entity_decode():
    html = '<meta property="og:title" content="Tom &amp; Jerry">'
    assert parse_og(html)["title"] == "Tom & Jerry"


def test_parse_og_missing_returns_empty():
    assert parse_og("<html></html>") == {"title": "", "description": ""}


def test_parse_og_truncates_long():
    long = "X" * 5000
    html = f'<meta property="og:description" content="{long}">'
    out = parse_og(html)
    assert len(out["description"]) <= 2000  # 截斷上限


# ── SSRF 守門 _is_safe_fetch_url(audit #1 零破壞版)──
from food.extract import _is_safe_fetch_url


def test_safe_fetch_url_allows_public_ip():
    assert _is_safe_fetch_url("http://8.8.8.8/") is True
    assert _is_safe_fetch_url("https://1.1.1.1/path?x=1") is True


def test_safe_fetch_url_blocks_loopback():
    assert _is_safe_fetch_url("http://127.0.0.1/") is False
    assert _is_safe_fetch_url("http://[::1]/") is False
    assert _is_safe_fetch_url("http://localhost/") is False


def test_safe_fetch_url_blocks_private_ranges():
    assert _is_safe_fetch_url("http://10.0.0.5/") is False
    assert _is_safe_fetch_url("http://192.168.1.1/") is False
    assert _is_safe_fetch_url("http://172.16.0.1/") is False


def test_safe_fetch_url_blocks_link_local_metadata():
    # 雲端 metadata endpoint
    assert _is_safe_fetch_url("http://169.254.169.254/latest/meta-data/") is False


def test_safe_fetch_url_blocks_nonhttp_schemes():
    assert _is_safe_fetch_url("file:///etc/passwd") is False
    assert _is_safe_fetch_url("ftp://example.com/") is False
    assert _is_safe_fetch_url("gopher://127.0.0.1:6379/") is False


def test_safe_fetch_url_blocks_empty_or_garbage():
    assert _is_safe_fetch_url("") is False
    assert _is_safe_fetch_url(None) is False
    assert _is_safe_fetch_url("not a url") is False


def test_http_get_blocks_unsafe_url_without_request(monkeypatch):
    from food import extract
    called = {"hit": False}
    def track(*a, **k):
        called["hit"] = True
        raise OSError("blocked")
    monkeypatch.setattr(extract.urllib.request, "urlopen", track)
    assert extract._http_get("http://127.0.0.1:8000/admin") is None
    assert called["hit"] is False  # 守門應在 urlopen 之前就 return


def test_deep_extract_blocks_unsafe_url_without_codex(monkeypatch):
    from food import extract
    called = {"hit": False}
    def track(*a, **k):
        called["hit"] = True
        raise OSError("blocked")
    monkeypatch.setattr(extract._subprocess, "run", track)
    assert extract.deep_extract_via_codex("http://169.254.169.254/") is None
    assert called["hit"] is False  # full-access codex 不應被叫到
