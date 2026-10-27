"""LINE Flex message traversal helpers."""
import json


_CHILD_KEYS = ("header", "hero", "body", "footer", "contents")
_TEXT_TYPES = {"text", "span"}


def texts(node: dict | list) -> list[str]:
    """Flatten text-bearing Flex nodes while ignoring actions and other metadata."""
    if isinstance(node, list):
        out = []
        for child in node:
            if isinstance(child, (dict, list)):
                out.extend(texts(child))
        return out
    if not isinstance(node, dict):
        return []

    out = []
    value = node.get("text")
    if node.get("type") in _TEXT_TYPES and isinstance(value, str) and value:
        out.append(value)
    for key in _CHILD_KEYS:
        child = node.get(key)
        if isinstance(child, (dict, list)):
            out.extend(texts(child))
    return out


def message_parts(msg: dict) -> tuple[str | None, int | None, list[str]]:
    """Return the alternate text, content type, and flattened message text."""
    metadata = msg.get("contentMetadata")
    if not isinstance(metadata, dict):
        metadata = {}
    alt = metadata.get("ALT_TEXT")
    if not isinstance(alt, str):
        alt = None
    content_type = msg.get("contentType")
    if not isinstance(content_type, int):
        content_type = None

    if content_type == 22:
        try:
            flex = json.loads(metadata["FLEX_JSON"])
        except (KeyError, TypeError, json.JSONDecodeError):
            flattened = []
        else:
            flattened = texts(flex) if isinstance(flex, (dict, list)) else []
    elif content_type == 0:
        text = msg.get("text")
        flattened = [text] if isinstance(text, str) and text else []
    else:
        flattened = []
    return alt, content_type, flattened


def is_spend(alt: str | None, texts: list[str]) -> bool:
    """Identify a CTBC spending notification by its alternate or lead text."""
    return (isinstance(alt, str) and "消費通知" in alt) or texts[:1] == ["刷卡通知"]
