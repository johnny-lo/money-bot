"""連結 → 文字 blob → {topic,tags} + 乾淨標題 → 入庫 HistoryVideo + 掛標籤。

回 (video_dict_or_None, reason)：
- 非 None → 入庫成功，含 _created（True=新增 / False=已收錄過）與 tags
- None    → reason 為提示字串（呼叫端回卡片）

最大化複用美食抽取基建：classify_platform + food.extract.from_url（yt-dlp 抓 title/uploader/desc）。
"""
from food.links import classify_platform
from food.extract import from_url as _extract_from_url
from video import repo
from video.extract import meta_from_text


_NO_TITLE_REASON = "抽不到影片標題"


def from_url(url: str, *, caption: str = "") -> tuple[dict | None, str]:
    """從連結入庫影片。caption=使用者去 URL 後的文字註解（若有，優先併入餵 AI）。"""
    platform = classify_platform(url)

    try:
        blob = _extract_from_url(url, platform)
    except Exception as ex:
        return None, f"連結抽取失敗：{ex}"

    pieces = [p for p in (caption.strip() if caption else "", blob or "") if p]
    text = "\n".join(pieces)

    meta = {"topic": "", "tags": []}
    if text:
        try:
            meta = meta_from_text(text)
        except Exception:
            meta = {"topic": "", "tags": []}   # AI 失敗不擋入庫，標題仍可退 blob 第一行

    # 標題：優先 blob 第一行（yt-dlp 第一段就是 title）；空白防 IndexError
    title = ""
    if blob:
        title = (blob.strip().splitlines() or [""])[0].strip()
    if not title:
        return None, _NO_TITLE_REASON

    topic = meta.get("topic") or None        # 空字串存 None
    rec, created = repo.add_video(title, url, topic=topic, platform=platform)
    for tag in meta.get("tags", []):
        repo.add_tag(rec["id"], tag)

    rec["_created"] = created
    rec["tags"] = meta.get("tags", [])       # 回傳前帶上建議標籤，省一次查詢
    return rec, ""
