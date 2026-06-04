from models import Recipe


def test_recipe_table_and_columns():
    assert Recipe.__tablename__ == "recipes"
    cols = {c.name for c in Recipe.__table__.columns}
    assert cols == {
        "id", "name", "url", "platform", "discord_message_id", "created_at"
    }


def test_recipe_url_is_unique():
    assert Recipe.__table__.columns["url"].unique is True


def test_recipe_url_indexed():
    assert Recipe.__table__.columns["url"].index is True
    assert Recipe.__table__.columns["discord_message_id"].index is True
