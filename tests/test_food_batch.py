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


from food.ingest import split_lines, is_batch, take_capped, BATCH_LINE_CAP


def test_split_lines_drops_blank_and_whitespace():
    text = "鼎泰豐\n\n  \n映客\n   海底撈  "
    assert split_lines(text) == ["鼎泰豐", "映客", "海底撈"]


def test_split_lines_empty():
    assert split_lines("") == []
    assert split_lines("   \n  \n") == []


def test_is_batch_two_or_more_lines():
    assert is_batch("鼎泰豐\n映客") is True
    assert is_batch("鼎泰豐\n\n映客\n海底撈") is True


def test_is_batch_single_line_false():
    assert is_batch("鼎泰豐 信義店") is False
    assert is_batch("鼎泰豐\n\n  \n") is False   # 只有一個非空行
    assert is_batch("") is False


def test_take_capped_under_cap():
    lines = ["a", "b", "c"]
    kept, dropped = take_capped(lines)
    assert kept == ["a", "b", "c"]
    assert dropped == 0


def test_take_capped_over_cap_reports_remainder():
    lines = [f"店{i}" for i in range(70)]
    kept, dropped = take_capped(lines)
    assert len(kept) == BATCH_LINE_CAP == 60
    assert kept[0] == "店0"
    assert kept[-1] == "店59"
    assert dropped == 10


from food.ingest import bucket_line


def _place(city="台北市"):
    return {"place_id": "p1", "name": "鼎泰豐 信義店", "city": city}


def test_bucket_ok_needs_area_and_city():
    fields = {"name": "鼎泰豐", "area": "信義"}
    assert bucket_line(fields, _place(city="台北市")) == "ok"


def test_bucket_review_when_no_area():
    fields = {"name": "鼎泰豐", "area": ""}
    assert bucket_line(fields, _place(city="台北市")) == "review"


def test_bucket_review_when_google_no_city():
    fields = {"name": "鼎泰豐", "area": "信義"}
    assert bucket_line(fields, _place(city=None)) == "review"
    assert bucket_line(fields, _place(city="")) == "review"


def test_bucket_ok_overseas_country_only():
    fields = {"name": "一蘭", "area": "福岡"}
    assert bucket_line(fields, {"place_id": "p2", "name": "一蘭 天神店", "city": "", "country": "日本"}) == "ok"


def test_bucket_fail_when_no_name():
    fields = {"name": "", "area": ""}
    assert bucket_line(fields, _place()) == "fail"


def test_bucket_fail_when_no_place():
    fields = {"name": "鼎泰豐", "area": "信義"}
    assert bucket_line(fields, None) == "fail"


from food.ingest import dedupe_resolved


def _r(place_id, status, name="店", raw="raw"):
    return {
        "place": {"place_id": place_id, "name": name, "city": "台北市"},
        "fields": {"name": name, "area": "信義", "recommended_items": "", "cuisine_type": ""},
        "area_given": True,
        "status": status,
        "raw": raw,
    }


def test_dedupe_collapses_same_place_id():
    resolved = [_r("p1", "想去", raw="A"), _r("p1", "想去", raw="B"), _r("p2", "想去")]
    out = dedupe_resolved(resolved)
    ids = [r["place"]["place_id"] for r in out]
    assert ids == ["p1", "p2"]               # 保序、p1 只出現一次


def test_dedupe_status_upgrade_to_visited():
    resolved = [_r("p1", "想去"), _r("p1", "去過")]
    out = dedupe_resolved(resolved)
    assert len(out) == 1
    assert out[0]["status"] == "去過"


def test_dedupe_visited_first_then_wishlist_stays_visited():
    resolved = [_r("p1", "去過"), _r("p1", "想去")]
    out = dedupe_resolved(resolved)
    assert len(out) == 1
    assert out[0]["status"] == "去過"


def test_dedupe_keeps_first_fields():
    resolved = [_r("p1", "想去", raw="first"), _r("p1", "去過", raw="second")]
    out = dedupe_resolved(resolved)
    assert out[0]["raw"] == "first"
