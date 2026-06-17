from models import HistoryVideo, VideoTag


def test_history_video_table_and_columns():
    assert HistoryVideo.__tablename__ == "history_videos"
    cols = {c.name for c in HistoryVideo.__table__.columns}
    assert cols == {
        "id", "title", "url", "topic", "channel",
        "platform", "discord_message_id", "created_at",
    }


def test_history_video_url_unique_and_indexed():
    assert HistoryVideo.__table__.columns["url"].unique is True
    assert HistoryVideo.__table__.columns["url"].index is True
    assert HistoryVideo.__table__.columns["topic"].index is True
    assert HistoryVideo.__table__.columns["discord_message_id"].index is True


def test_video_tag_table_and_columns():
    assert VideoTag.__tablename__ == "video_tags"
    cols = {c.name for c in VideoTag.__table__.columns}
    assert cols == {"id", "video_id", "tag"}


def test_video_tag_fk_cascade():
    fks = list(VideoTag.__table__.columns["video_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "history_videos"
    assert fks[0].ondelete == "CASCADE"
    assert VideoTag.__table__.columns["video_id"].index is True
    assert VideoTag.__table__.columns["tag"].index is True
