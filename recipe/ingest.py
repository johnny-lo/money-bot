"""連結 → 文字 blob → 乾淨菜名 → 入庫 Recipe 的 orchestrator。

回 (recipe_dict_or_None, missing_reason)：
- 非 None → 入庫成功，含 _created（True=新增 / False=已收錄過）
- None    → gmaps / 抽不到菜名（呼叫端回提示，必要時建 pending 卡）

最大化複用美食現成抽取基建：classify_platform + food.extract.from_url。
"""
from food.links import classify_platform
from food.extract import from_url as _extract_from_url
from recipe import repo
from recipe.extract import name_from_text


_GMAPS_REASON = "這看起來是地點不是食譜，要收店家請丟 #🍜-美食"
_NO_NAME_REASON = "抽不到菜名"


def from_url(url: str, *, caption: str = "") -> tuple[dict | None, str]:
    """從連結入庫食譜。caption 是使用者去 URL 後的文字註解（若有，優先併入）。"""
    platform = classify_platform(url)
    if platform == "gmaps":
        return None, _GMAPS_REASON

    try:
        blob = _extract_from_url(url, platform)
    except Exception as ex:
        return None, f"連結抽取失敗：{ex}"

    # None-blob guard（比照 food/ingest.py:77）
    pieces = [p for p in (caption.strip() if caption else "", blob or "") if p]
    text = "\n".join(pieces)

    name = ""
    if text:
        try:
            name = name_from_text(text)
        except Exception as ex:
            return None, f"菜名解析失敗：{ex}"

    # codex 抽不出 → 退用 blob 第一行當暫定名（blob 可能全是空白 → splitlines() 為空,須防 IndexError）
    if not name and blob:
        name = (blob.strip().splitlines() or [""])[0].strip()

    if not name:
        return None, _NO_NAME_REASON

    rec, created = repo.add_recipe(name, url, platform)
    rec["_created"] = created
    return rec, ""
