"""連結文字 blob → {topic, tags}（codex），以及 YouTube 縮圖。

- parse_video_meta：純函式，把 codex 回應字串解析成 {topic, tags}（壞 JSON/缺欄位回空）
- meta_from_text：用 codex_text 從一段文字判主題+標籤
- youtube_thumbnail：reuse food.extract.parse_video_id → 縮圖網址（非 YouTube 回 None）
"""
import json

from codex_cli import codex_text
from food.extract import parse_video_id


_VIDEO_PROMPT = (
    "以下是一支歷史教學影片的標題與描述。請判斷它的「主題」與「標籤」。\n"
    "規則：\n"
    "- topic：給單一最貼切的主題分類（例：唐朝、明清、世界大戰、台灣史），這是書架，一支只放一格；判斷不出回空字串。\n"
    "- tags：給 3~5 個跨主題的關鍵字標籤（例：經濟、戰爭、制度、人物），用繁體中文、不重複；判斷不出回空陣列。\n"
    "只回 JSON、不要 markdown 標籤：\n"
    '{{"topic":"主題(判斷不出就空字串)","tags":["標籤1","標籤2"]}}\n\n'
    "內容：\n{text}"
)

_MAX_TAGS = 5


def _strip_fence(t: str) -> str:
    t = (t or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def parse_video_meta(raw: str) -> dict:
    """codex 回應 → {topic:str, tags:[str]}。壞 JSON / 非 dict / 缺欄位皆安全降級。"""
    try:
        d = json.loads(_strip_fence(raw))
    except (ValueError, TypeError):
        return {"topic": "", "tags": []}
    if not isinstance(d, dict):
        return {"topic": "", "tags": []}
    topic = d.get("topic")
    topic = topic.strip() if isinstance(topic, str) else ""
    tags: list[str] = []
    raw_tags = d.get("tags")
    if isinstance(raw_tags, list):
        for x in raw_tags:
            s = x.strip() if isinstance(x, str) else ""
            if s and s not in tags:
                tags.append(s)
    return {"topic": topic, "tags": tags[:_MAX_TAGS]}


def meta_from_text(text: str) -> dict:
    """一段文字 → {topic, tags}（codex）。抽不到回空。"""
    return parse_video_meta(codex_text(_VIDEO_PROMPT.format(text=text)))


def youtube_thumbnail(url: str) -> str | None:
    """YouTube URL → hqdefault 縮圖網址；非 YouTube / 解不出回 None。"""
    vid = parse_video_id(url)
    return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if vid else None
