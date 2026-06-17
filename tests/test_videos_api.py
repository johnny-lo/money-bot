import pytest
from pydantic import ValidationError
from routes.videos import UpdateBody, TagBody


def test_update_body_allows_partial():
    assert UpdateBody(title="新標題").title == "新標題"
    assert UpdateBody(topic="唐朝").topic == "唐朝"
    assert UpdateBody().title is None        # 兩個都可選


def test_update_body_blank_title_rejected():
    with pytest.raises(ValidationError):
        UpdateBody(title="   ")


def test_tag_body_blank_rejected():
    with pytest.raises(ValidationError):
        TagBody(tag="  ")
    assert TagBody(tag=" 經濟 ").tag == "經濟"   # strip
