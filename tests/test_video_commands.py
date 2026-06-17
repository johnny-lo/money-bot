from video.commands import parse_reply_command, CHEAT_SHEET


def test_rename_when_no_marker():
    assert parse_reply_command("唐朝的經濟與賦稅") == {
        "mode": "rename", "title": "唐朝的經濟與賦稅",
    }


def test_empty_is_noop():
    assert parse_reply_command("   ") == {"mode": "noop"}
    assert parse_reply_command("") == {"mode": "noop"}


def test_set_topic_only():
    out = parse_reply_command("#唐朝")
    assert out == {"mode": "edit", "topic": "唐朝", "add": [], "remove": []}


def test_add_with_plus_and_bare_tokens():
    # + 之後的裸 token 也算新增
    out = parse_reply_command("+經濟 戰爭")
    assert out == {"mode": "edit", "topic": None, "add": ["經濟", "戰爭"], "remove": []}


def test_remove():
    out = parse_reply_command("-制度")
    assert out == {"mode": "edit", "topic": None, "add": [], "remove": ["制度"]}


def test_mixed_all_ops():
    out = parse_reply_command("#唐朝 +經濟 戰爭 -制度")
    assert out == {
        "mode": "edit", "topic": "唐朝",
        "add": ["經濟", "戰爭"], "remove": ["制度"],
    }


def test_marker_only_no_payload_is_edit_with_nothing():
    # 只打一個 "+"（無內容）→ edit 但什麼也沒帶（handler 視為 noop）
    out = parse_reply_command("+")
    assert out == {"mode": "edit", "topic": None, "add": [], "remove": []}


def test_cheat_sheet_mentions_all_four_ops():
    for marker in ("#", "+", "-"):
        assert marker in CHEAT_SHEET
    assert "改標題" in CHEAT_SHEET
