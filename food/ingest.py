"""美食抽取 → Places → 入庫 → 事後雷點 的 orchestrator。

回傳 (place_dict_or_None, missing_reason)：
- place_dict_or_None 非 None 代表入庫成功，含 _created（True=新增 / False=更新既有）
- place_dict_or_None None 代表缺資訊或查不到，呼叫端應建 pending 卡

雷點摘要採事後加值（best-effort），失敗不影響入庫。
"""
from food import extract
from food.places import search_text, caution_for_place_id
from food.repo import upsert_place, update_caution


def from_image(image_bytes: bytes, mime_type: str = "image/jpeg",
               *, source_url: str | None = None) -> tuple[dict | None, str]:
    try:
        fields = extract.from_image(image_bytes, mime_type=mime_type)
    except Exception as ex:
        return None, f"截圖辨識失敗：{ex}"
    return _from_fields(fields, source_url=source_url)


def from_text(text: str, *, source_url: str | None = None) -> tuple[dict | None, str]:
    if not text or not text.strip():
        return None, "沒有可解析的文字"
    try:
        fields = extract.from_text(text.strip())
    except Exception as ex:
        return None, f"文字解析失敗：{ex}"
    return _from_fields(fields, source_url=source_url)


def _from_fields(fields: dict, *, source_url: str | None) -> tuple[dict | None, str]:
    name = (fields.get("name") or "").strip()
    if not name:
        return None, "抽不到店名"
    query = f"{name} {fields.get('area') or ''}".strip()
    try:
        place = search_text(query)
    except Exception as ex:
        return None, f"查 Google 失敗：{ex}"
    if not place:
        return None, f"Google 找不到「{query}」"
    p, created = upsert_place(
        place,
        recommended_items=fields.get("recommended_items") or None,
        cuisine_type=fields.get("cuisine_type") or None,
        source_url=source_url,
    )
    # 事後加值：雷點摘要 best-effort
    try:
        c = caution_for_place_id(place["place_id"])
        if c:
            update_caution(p["id"], c)
            p["caution_summary"] = c
    except Exception:
        pass
    p["_created"] = created
    return p, ""
