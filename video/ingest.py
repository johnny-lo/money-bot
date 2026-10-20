"""連結 → 文字 blob → {topic,tags} + 乾淨標題 → 入庫 HistoryVideo + 掛標籤。

回 (video_dict_or_None, reason)：
- 非 None → 入庫成功，含 _created（True=新增 / False=已收錄過）與 tags
- None    → reason 為提示字串（呼叫端回卡片）

兩條抽取路徑，依 video.extract.kind_of(platform) 分：
- 影片（youtube／instagram／tiktok／facebook）：複用美食抽取基建 food.extract.from_url（yt-dlp 抓 title/uploader/desc），
  標題取 blob 第一行
- 文章（其餘）：video.extract.fetch_html 用瀏覽器 UA 抓網頁 → article_fields 抽標題／描述／內文，
  food.extract 不經手：美食模組共用它，動它會連動美食的抽取行為
"""
from food.links import classify_platform
from food.extract import from_url as _extract_from_url
from autofix import sensors
from video import repo
from video.extract import article_fields, fetch_html, kind_of, meta_from_text


_NO_TITLE_REASON = "抽不到標題（連結打不開，或頁面沒有標題）"


def _join(*pieces: str) -> str:
    return "\n".join(p for p in pieces if p)


def _video_material(url: str, platform: str) -> tuple[str, str]:
    """影片連結 → (標題, 餵 AI 的文字)。標題取 blob 第一行（yt-dlp 第一段就是 title）。"""
    blob = _extract_from_url(url, platform) or ""
    title = (blob.strip().splitlines() or [""])[0].strip()   # 空白防 IndexError
    return title, blob


def _article_material(url: str) -> tuple[str, str]:
    """文章連結 → (標題, 餵 AI 的文字)。抓不到內文時只剩標題＋描述，抓不到網頁則兩者皆空。"""
    fields = article_fields(fetch_html(url))
    return fields["title"], _join(fields["title"], fields["description"], fields["text"])


def from_url(url: str, *, caption: str = "") -> tuple[dict | None, str]:
    """從連結入庫影片或文章。caption=使用者去 URL 後的文字註解（若有，優先併入餵 AI）。"""
    platform = classify_platform(url)
    kind = kind_of(platform)

    try:
        title, material = (_video_material(url, platform) if kind == "video"
                           else _article_material(url))
    except Exception as ex:
        sensors.extract_failed("video", platform, url, ex)
        return None, f"連結抽取失敗：{ex}"
    sensors.extract_ok("video", platform)

    if not title:
        return None, _NO_TITLE_REASON

    text = _join(caption.strip() if caption else "", material)
    meta = {"topic": "", "tags": []}
    try:
        meta = meta_from_text(text) if kind == "video" else meta_from_text(text, kind)
    except Exception:
        pass   # AI 失敗不擋入庫，標題照用抽到的

    topic = meta.get("topic") or None        # 空字串存 None
    rec, created = repo.add_video(title, url, topic=topic, platform=platform)
    for tag in meta.get("tags", []):
        repo.add_tag(rec["id"], tag)

    rec["_created"] = created
    rec["tags"] = meta.get("tags", [])       # 回傳前帶上建議標籤，省一次查詢
    return rec, ""
