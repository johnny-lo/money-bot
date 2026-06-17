from models import HistoryVideo
from video.repo import to_dict


def _vid(**kw):
    v = HistoryVideo(**kw)
    if v.id is None:
        v.id = 1
    return v


def test_to_dict_youtube_has_thumbnail():
    v = _vid(title="唐朝", url="https://youtu.be/dQw4w9WgXcQ",
             topic="唐朝", channel="某頻道", platform="youtube")
    d = to_dict(v, tags=["經濟", "戰爭"])
    assert d["title"] == "唐朝"
    assert d["topic"] == "唐朝"
    assert d["tags"] == ["經濟", "戰爭"]
    assert d["thumbnail"] == "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_to_dict_non_youtube_thumbnail_none_and_default_tags():
    v = _vid(title="x", url="https://www.bilibili.com/video/BV1", platform="other")
    d = to_dict(v)
    assert d["thumbnail"] is None
    assert d["tags"] == []        # 沒帶 tags → 預設空陣列
