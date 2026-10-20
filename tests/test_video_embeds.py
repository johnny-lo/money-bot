from discordbot.embeds import video_card_embed, video_help_embed, video_missing_embed
from video.commands import CHEAT_SHEET


def test_card_has_cheatsheet_and_fields():
    e = video_card_embed(
        {"id": 7, "title": "唐朝的經濟", "topic": "唐朝", "platform": "youtube",
         "url": "https://youtu.be/x", "tags": ["經濟", "戰爭"]},
        created=True,
    )
    blob = e.title + (e.footer.text or "") + " ".join(
        f"{f.name}{f.value}" for f in e.fields
    )
    assert "唐朝的經濟" in e.title
    assert "唐朝" in blob and "經濟" in blob       # topic + tags 有顯示
    assert CHEAT_SHEET in blob                      # 小抄印在卡片上


def test_help_embed_is_cheatsheet():
    e = video_help_embed()
    assert CHEAT_SHEET in (e.description or "")


def _flat(e):
    return (e.title or "") + (e.description or "") + (e.footer.text or "" if e.footer else "") + " ".join(
        f"{f.name}{f.value}" for f in e.fields)


def test_card_title_marks_video_by_kind():
    e = video_card_embed({"id": 1, "title": "唐朝", "kind": "video", "url": "https://youtu.be/x"})
    assert e.title.startswith("🎥") and "📄" not in e.title


def test_card_title_marks_article_by_kind():
    e = video_card_embed({"id": 2, "title": "唐朝的經濟", "kind": "article",
                          "url": "https://example.com/a", "topic": "唐朝", "tags": ["經濟"]},
                         created=False)
    assert e.title.startswith("📄") and "唐朝的經濟" in e.title and "已收錄過" in e.title
    assert CHEAT_SHEET in _flat(e)


def test_card_kind_falls_back_to_platform_when_missing():
    video = video_card_embed({"id": 1, "title": "t", "platform": "youtube"})
    article = video_card_embed({"id": 2, "title": "t", "platform": "other"})
    assert video.title.startswith("🎥") and article.title.startswith("📄")


def test_help_embed_covers_video_and_article():
    e = video_help_embed()
    assert "影片" in e.title and "文章" in e.title
    assert CHEAT_SHEET in (e.description or "")


def test_missing_embed_wording_covers_both_kinds():
    e = video_missing_embed("")
    assert "影片" in e.description and "文章" in e.description
    assert video_missing_embed("連結打不開").description == "連結打不開"
