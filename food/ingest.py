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


def from_url(url: str, *, caption: str = "") -> tuple[dict | None, str]:
    """從連結入庫。caption 是使用者去 URL 後的文字註解(若有,優先採用)。

    流程:
      1) extract.from_url(yt-dlp 主 + og fetch 備援)→ blob
      2) caption + blob 餵 extract.from_text(codex)→ fields
      3) 若 fields['name'] 為空 → 走深度振查(Task 7B 的 deep_extract_via_codex)
      4) _from_fields → search_text + upsert + 雷點 best-effort
    """
    from food.links import classify_platform
    platform = classify_platform(url)
    try:
        blob = extract.from_url(url, platform)
    except Exception as ex:
        return None, f"連結抽取失敗:{ex}"
    pieces = [p for p in (caption.strip() if caption else "", blob or "") if p]
    if pieces:
        text = "\n".join(pieces)
        try:
            fields = extract.from_text(text)
        except Exception as ex:
            return None, f"文字解析失敗:{ex}"
    else:
        fields = {"name": "", "area": "", "recommended_items": "", "cuisine_type": ""}
    # 加碼第 3 層:純文字抽不到店名 → 動用深度振查(看圖 + 搜尋交叉驗證)
    if not fields.get("name"):
        try:
            deep = extract.deep_extract_via_codex(url, hint=caption or "")
        except Exception as ex:
            deep = None
            print(f"⚠️ deep_extract 失敗:{ex}")
        if deep and deep.get("name"):
            fields = deep
    if not fields.get("name"):
        return None, f"{platform} 連結抽不到店名"
    return _from_fields(fields, source_url=url)
