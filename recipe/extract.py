"""連結文字 blob → 乾淨菜名。

- parse_name_json：純函式，把 codex 回應字串解析成菜名（markdown 去殼、缺欄位/壞 JSON 回空字串）
- name_from_text：用 codex_text 從一段文字抽出菜名
"""
import json

from codex_cli import codex_text


_RECIPE_PROMPT = (
    "請從以下內容判斷這是哪一道料理，抽出乾淨的菜名。\n"
    "規則：去掉誇張標題/頻道名/emoji/集數/「教學」「食譜」等贅字，只留料理本身的名字；\n"
    "判斷不出菜名就回空字串。只回 JSON、不要 markdown 標籤：\n"
    '{{"name":"乾淨菜名(判斷不出就空字串)"}}\n\n'
    "內容：\n{text}"
)


def parse_name_json(raw: str) -> str:
    """把 codex 回應字串清成乾淨菜名。markdown 去殼、缺欄位/壞 JSON 皆回空字串、strip。"""
    t = (raw or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    try:
        d = json.loads(t.strip())
    except (ValueError, TypeError):
        return ""
    if not isinstance(d, dict):
        return ""
    return (d.get("name") or "").strip()


def name_from_text(text: str) -> str:
    """一段文字 → 乾淨菜名（codex）。抽不到回空字串。"""
    return parse_name_json(codex_text(_RECIPE_PROMPT.format(text=text)))
