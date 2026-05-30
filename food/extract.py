"""影片/文字/截圖 → 店家欄位 JSON。

- parse_extracted_json：純函式，把 AI 回應字串解析成 {name, area, recommended_items, cuisine_type}
- from_text：用 codex_text 把純文字抽成欄位
- from_image：用 gemini_image 直接從截圖一步到位抽欄位
"""
import json

from gemini import gemini_image
from codex_cli import codex_text


_TEXT_PROMPT = (
    "請從以下文字內容中擷取店家資訊，只回 JSON、不要 markdown 標籤：\n"
    '{{"name":"店名(沒有就空字串)","area":"區域提示(縣市/城市)","'
    'recommended_items":"推薦品項(可空)","cuisine_type":"料理類型(可空)"}}\n\n'
    "文字內容：\n{text}"
)

_IMAGE_PROMPT = (
    "請從這張圖片擷取店家資訊，只回 JSON、不要 markdown 標籤：\n"
    '{"name":"店名(沒有就空字串)","area":"區域提示(縣市/城市)","'
    'recommended_items":"推薦品項(可空)","cuisine_type":"料理類型(可空)"}'
)


def parse_extracted_json(raw: str) -> dict:
    """把 AI 回應字串清成乾淨 dict。缺欄位以空字串補齊、首尾空白皆 strip。"""
    t = raw.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    d = json.loads(t.strip())
    return {
        "name": (d.get("name") or "").strip(),
        "area": (d.get("area") or "").strip(),
        "recommended_items": (d.get("recommended_items") or "").strip(),
        "cuisine_type": (d.get("cuisine_type") or "").strip(),
    }


def from_text(text: str) -> dict:
    """純文字 → 欄位（codex）。"""
    return parse_extracted_json(codex_text(_TEXT_PROMPT.format(text=text)))


def from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """截圖 → 欄位（Gemini Vision 一次到位）。"""
    return parse_extracted_json(gemini_image(_IMAGE_PROMPT, image_bytes, mime_type=mime_type))


import re as _re

_YT_ID_RE = _re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|v/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def parse_video_id(url: str) -> str | None:
    """從 YouTube URL 解出 11 碼 video id;非 YouTube 或解不出回 None。"""
    if not url:
        return None
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


from urllib.parse import unquote_plus as _unquote_plus

_GMAPS_PLACE_RE = _re.compile(r"/maps/place/([^/@?]+)")


def gmaps_place_name(url: str) -> str:
    """從 Google Maps URL 解出店名;解不出回空字串。"""
    if not url:
        return ""
    m = _GMAPS_PLACE_RE.search(url)
    if not m:
        return ""
    return _unquote_plus(m.group(1)).strip()
