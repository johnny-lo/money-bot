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
