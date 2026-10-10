from recipe.extract import parse_name_json


def test_parse_plain_json():
    assert parse_name_json('{"name":"蒜香奶油蝦"}') == "蒜香奶油蝦"


def test_parse_missing_name_returns_empty():
    assert parse_name_json('{}') == ""


def test_parse_null_name_returns_empty():
    assert parse_name_json('{"name":null}') == ""


def test_parse_whitespace_stripped():
    assert parse_name_json('  {"name":"  滷肉飯  "}  ') == "滷肉飯"


def test_parse_invalid_json_returns_empty():
    assert parse_name_json("這不是 JSON") == ""
    assert parse_name_json("") == ""


def test_parse_non_object_json_returns_empty():
    # 合法但非物件的 JSON（list/str/number/bool/null）也要回空字串,不可 AttributeError
    assert parse_name_json("[1,2,3]") == ""
    assert parse_name_json('"just a string"') == ""
    assert parse_name_json("42") == ""
    assert parse_name_json("true") == ""
    assert parse_name_json("null") == ""


import recipe.extract as rx


def test_name_from_text_strips_to_clean_name(monkeypatch):
    monkeypatch.setattr(rx, "codex_text",
                        lambda prompt, **kw: '{"name":"奶油蒜香雞腿排"}')
    assert rx.name_from_text("【超下飯】10分鐘奶油蒜香雞腿排教學 ft. 某頻道") == "奶油蒜香雞腿排"


def test_name_from_text_empty_when_codex_blank(monkeypatch):
    monkeypatch.setattr(rx, "codex_text", lambda prompt, **kw: '{"name":""}')
    assert rx.name_from_text("一段看不出菜名的旅遊 vlog 字幕") == ""


def test_name_from_text_passes_text_into_prompt(monkeypatch):
    seen = {}
    def fake(prompt, schema=None):
        seen["prompt"] = prompt
        seen["schema"] = schema
        return '{"name":"x"}'
    monkeypatch.setattr(rx, "codex_text", fake)
    rx.name_from_text("獨特字串ABC123")
    assert "獨特字串ABC123" in seen["prompt"]
    assert seen["schema"]["required"] == ["name"]
