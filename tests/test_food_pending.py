import food.pending as pending


def setup_function(_):
    pending.clear()


def test_remember_and_get():
    pending.remember("msg1", original_message_id="orig1", raw_text="hi",
                     missing_reason="no name")
    p = pending.get("msg1")
    assert p["bot_message_id"] == "msg1"
    assert p["original_message_id"] == "orig1"
    assert p["raw_text"] == "hi"
    assert p["missing_reason"] == "no name"


def test_consume_removes():
    pending.remember("msg2", original_message_id="o2")
    assert pending.consume("msg2") is not None
    assert pending.get("msg2") is None


def test_missing_returns_none():
    assert pending.get("nope") is None
    assert pending.consume("nope") is None


def test_int_and_str_keys_normalized():
    pending.remember(123, original_message_id=456)
    assert pending.get("123") is not None
    assert pending.consume(123) is not None
