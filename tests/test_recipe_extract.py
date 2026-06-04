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
