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


from food.ingest import strip_checkbox


def test_strip_checkbox_unchecked():
    assert strip_checkbox("- [ ] 鼎泰豐 (信義店)") == ("想去", "鼎泰豐 (信義店)")


def test_strip_checkbox_checked_lowercase():
    assert strip_checkbox("- [x] 映客 (台中") == ("去過", "映客 (台中")


def test_strip_checkbox_checked_uppercase():
    assert strip_checkbox("- [X] 海底撈") == ("去過", "海底撈")


def test_strip_checkbox_no_space_variant():
    assert strip_checkbox("-[x]鼎泰豐") == ("去過", "鼎泰豐")
    assert strip_checkbox("-[ ]海底撈") == ("想去", "海底撈")


def test_strip_checkbox_asterisk_bullet():
    assert strip_checkbox("* [ ] 這家拉麵超好吃 (台中)") == ("想去", "這家拉麵超好吃 (台中)")
    assert strip_checkbox("* [x] 火鍋店") == ("去過", "火鍋店")


def test_strip_checkbox_no_prefix_is_wishlist():
    assert strip_checkbox("海底撈") == ("想去", "海底撈")


def test_strip_checkbox_plain_dash_bullet_no_checkbox():
    assert strip_checkbox("- 鼎泰豐") == ("想去", "鼎泰豐")


def test_strip_checkbox_keeps_trailing_paren_unclosed():
    assert strip_checkbox("- [x] 映客牛蒡天婦羅 (台中") == ("去過", "映客牛蒡天婦羅 (台中")
