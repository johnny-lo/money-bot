from discordbot.embeds import video_card_embed, video_help_embed
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
