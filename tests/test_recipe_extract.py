from recipe.extract import parse_name_json


def test_parse_plain_json():
    assert parse_name_json('{"name":"蒜香奶油蝦"}') == "蒜香奶油蝦"


def test_parse_with_markdown_fences():
    raw = "```json\n{\"name\":\"番茄炒蛋\"}\n```"
    assert parse_name_json(raw) == "番茄炒蛋"


def test_parse_bare_triple_fence():
    raw = "```\n{\"name\":\"麻婆豆腐\"}\n```"
    assert parse_name_json(raw) == "麻婆豆腐"


def test_parse_missing_name_returns_empty():
    assert parse_name_json('{}') == ""


def test_parse_null_name_returns_empty():
    assert parse_name_json('{"name":null}') == ""


def test_parse_whitespace_stripped():
    assert parse_name_json('  {"name":"  滷肉飯  "}  ') == "滷肉飯"


def test_parse_invalid_json_returns_empty():
    assert parse_name_json("這不是 JSON") == ""
    assert parse_name_json("") == ""


import recipe.extract as rx


def test_name_from_text_strips_to_clean_name(monkeypatch):
    monkeypatch.setattr(rx, "codex_text",
                        lambda prompt: '```json\n{"name":"奶油蒜香雞腿排"}\n```')
    assert rx.name_from_text("【超下飯】10分鐘奶油蒜香雞腿排教學 ft. 某頻道") == "奶油蒜香雞腿排"


def test_name_from_text_empty_when_codex_blank(monkeypatch):
    monkeypatch.setattr(rx, "codex_text", lambda prompt: '{"name":""}')
    assert rx.name_from_text("一段看不出菜名的旅遊 vlog 字幕") == ""


def test_name_from_text_passes_text_into_prompt(monkeypatch):
    seen = {}
    def fake(prompt):
        seen["prompt"] = prompt
        return '{"name":"x"}'
    monkeypatch.setattr(rx, "codex_text", fake)
    rx.name_from_text("獨特字串ABC123")
    assert "獨特字串ABC123" in seen["prompt"]
