"""LINE Flex 訊息的走訪工具。"""
import json


_CHILD_KEYS = ("header", "hero", "body", "footer", "contents")
_TEXT_TYPES = {"text", "span"}


def texts(node: dict | list) -> list[str]:
    """依 Flex 顯示順序攤平文字節點，略過動作與其他中繼資料。"""
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
    """取出替代文字、內容類型與攤平後的訊息文字。"""
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
    """依替代文字或第一段文字辨認中信消費通知。"""
    return (isinstance(alt, str) and "消費通知" in alt) or texts[:1] == ["刷卡通知"]
