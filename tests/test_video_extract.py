from video.extract import parse_video_meta, youtube_thumbnail


def test_parse_clean_json():
    out = parse_video_meta('{"topic":"唐朝","tags":["經濟","戰爭","制度"]}')
    assert out == {"topic": "唐朝", "tags": ["經濟", "戰爭", "制度"]}


def test_parse_strips_markdown_fence():
    out = parse_video_meta('```json\n{"topic":"明清","tags":["科舉"]}\n```')
    assert out == {"topic": "明清", "tags": ["科舉"]}


def test_parse_dedupes_and_caps_five_tags():
    out = parse_video_meta('{"topic":"x","tags":["a","a","b","c","d","e","f"]}')
    assert out["tags"] == ["a", "b", "c", "d", "e"]   # 去重後截 5


def test_parse_bad_json_returns_empty():
    assert parse_video_meta("看不懂") == {"topic": "", "tags": []}
    assert parse_video_meta('{"topic":123}') == {"topic": "", "tags": []}  # tags 缺 → []


def test_parse_non_dict_returns_empty():
    assert parse_video_meta('["a","b"]') == {"topic": "", "tags": []}


def test_youtube_thumbnail():
    assert youtube_thumbnail("https://youtu.be/dQw4w9WgXcQ") == \
        "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert youtube_thumbnail("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == \
        "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_youtube_thumbnail_non_youtube_is_none():
    assert youtube_thumbnail("https://www.bilibili.com/video/BV1xx") is None
    assert youtube_thumbnail("") is None
