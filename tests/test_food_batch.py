from food.extract import parse_place_list_json, _strip_markdown_fence


def test_parse_place_list_json_basic():
    raw = (
        '[{"name":"鼎泰豐","area":"信義","recommended_items":"小籠包","cuisine_type":"中式"},'
        '{"name":"映客牛蒡天婦羅","area":"台中","recommended_items":"","cuisine_type":"天婦羅"}]'
    )
    out = parse_place_list_json(raw, 2)
    assert len(out) == 2
    assert out[0] == {"name": "鼎泰豐", "area": "信義",
                      "recommended_items": "小籠包", "cuisine_type": "中式"}
    assert out[1]["name"] == "映客牛蒡天婦羅"
    assert out[1]["recommended_items"] == ""


def test_parse_place_list_json_strips_markdown_fence():
    raw = '```json\n[{"name":"A"}]\n```'
    out = parse_place_list_json(raw, 1)
    assert out[0]["name"] == "A"
    assert out[0]["area"] == ""
    assert out[0]["recommended_items"] == ""
    assert out[0]["cuisine_type"] == ""


def test_parse_place_list_json_pads_short_array_with_empty():
    raw = '[{"name":"只有一家","area":"台北"}]'
    out = parse_place_list_json(raw, 3)
    assert len(out) == 3
    assert out[0]["name"] == "只有一家"
    assert out[1] == {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}
    assert out[2]["name"] == ""


def test_parse_place_list_json_truncates_long_array():
    raw = '[{"name":"X"},{"name":"Y"},{"name":"Z"}]'
    out = parse_place_list_json(raw, 2)
    assert len(out) == 2
    assert [o["name"] for o in out] == ["X", "Y"]


def test_parse_place_list_json_whitespace_stripped_per_field():
    raw = '[{"name":"  甲  ","area":" 台中 "}]'
    out = parse_place_list_json(raw, 1)
    assert out[0]["name"] == "甲"
    assert out[0]["area"] == "台中"


def test_parse_place_list_json_bad_json_returns_all_empty():
    out = parse_place_list_json("這不是 JSON", 2)
    assert len(out) == 2
    assert out[0] == {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}
    assert out[1] == {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}


def test_strip_markdown_fence_variants():
    assert _strip_markdown_fence('```json\n{"a":1}\n```') == '{"a":1}'
    assert _strip_markdown_fence('```\n[]\n```') == '[]'
    assert _strip_markdown_fence('  {"a":1}  ') == '{"a":1}'
    assert _strip_markdown_fence('') == ''


def test_parse_place_list_json_zero_n():
    assert parse_place_list_json("[]", 0) == []
    assert parse_place_list_json("這不是 JSON", 0) == []


def test_parse_place_list_json_non_dict_element():
    out = parse_place_list_json('[{"name":"A"}, "not a dict", {"name":"C"}]', 3)
    assert len(out) == 3
    assert out[0]["name"] == "A"
    assert out[1] == {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}
    assert out[2]["name"] == "C"
