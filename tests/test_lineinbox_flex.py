import json
from pathlib import Path

from lineinbox.flex import is_spend, message_parts, texts


FIXTURES = Path(__file__).parent / "fixtures" / "ctbc_line"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_texts_only_collects_text_and_span_nodes():
    node = {
        "type": "bubble",
        "header": {"type": "text", "text": "header", "url": "https://example.invalid/header"},
        "hero": {"type": "text", "text": "hero", "url": "https://example.invalid/hero"},
        "body": {
            "type": "box",
            "contents": [
                {"type": "text", "text": "body"},
                {"type": "span", "text": "span"},
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "button label",
                        "uri": "https://example.invalid/action",
                    },
                },
            ],
        },
        "footer": {"type": "text", "text": "footer"},
        "contents": [{"type": "text", "text": "root contents"}],
        "action": {"type": "message", "text": "action text"},
        "url": "https://example.invalid/root",
    }

    assert texts(node) == ["header", "hero", "body", "span", "footer", "root contents"]


def test_message_parts_flex_and_text_message():
    alt, content_type, flattened = message_parts(_fixture("store"))

    assert alt == "🔔LINE Pay聯名卡消費通知🔔"
    assert content_type == 22
    assert flattened[:10] == [
        "刷卡通知",
        "NT$1,280",
        "卡末四碼：",
        "1234",
        "交易時間：",
        "2026/09/05  19:42",
        "商店名稱：",
        "ＸＸ炸雞－測試店",
        "*商店名稱僅供參考，實際以帳單為準",
        "（說明文字）",
    ]
    assert message_parts({"contentType": 0, "text": "hi"}) == (None, 0, ["hi"])
    assert message_parts({
        "contentType": 22,
        "contentMetadata": {"ALT_TEXT": "alt", "FLEX_JSON": "{"},
    }) == ("alt", 22, [])


def test_is_spend_uses_first_flex_text_or_alt_text():
    store_alt, _, store_texts = message_parts(_fixture("store"))
    deposit_alt, _, deposit_texts = message_parts(_fixture("deposit"))

    assert is_spend(store_alt, store_texts) is True
    assert is_spend(deposit_alt, deposit_texts) is False
    assert is_spend("這是消費通知", ["其他內容"]) is True
    assert is_spend(None, ["刷卡通知", "NT$1"]) is True
    assert is_spend(None, ["其他內容", "刷卡通知"]) is False
