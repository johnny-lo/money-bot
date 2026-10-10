"""recommended_for_place_id：推薦菜的形狀由 schema 保證，分隔符與上限由程式負責。"""
import codex_cli
from food import places


def _reviews(monkeypatch, texts):
    monkeypatch.setattr(places, "fetch_reviews",
                        lambda pid: [{"text": {"text": t}} for t in texts])


def test_dishes_joined_with_dunhao_and_capped_at_five(monkeypatch):
    _reviews(monkeypatch, ["牛肉麵很讚"])
    seen = {}

    def fake(prompt, schema=None):
        seen["schema"] = schema
        return '{"dishes":["牛肉麵"," 小菜 ","","滷蛋","豆干","海帶","貢丸"]}'
    monkeypatch.setattr(codex_cli, "codex_text", fake)
    assert places.recommended_for_place_id("p") == "牛肉麵、小菜、滷蛋、豆干、海帶"
    assert seen["schema"]["required"] == ["dishes"]


def test_no_dishes_mentioned_gives_empty_string(monkeypatch):
    _reviews(monkeypatch, ["服務很好"])
    monkeypatch.setattr(codex_cli, "codex_text", lambda p, schema=None: '{"dishes":[]}')
    assert places.recommended_for_place_id("p") == ""
