"""美食抽取 → Places → 入庫 → 事後雷點 的 orchestrator。

回傳 (place_dict_or_None, missing_reason)：
- place_dict_or_None 非 None 代表入庫成功，含 _created（True=新增 / False=更新既有）
- place_dict_or_None None 代表缺資訊或查不到，呼叫端應建 pending 卡

雷點摘要採事後加值（best-effort），失敗不影響入庫。
"""
import re
from food import extract
from food.links import classify_platform
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


# 勾選框前綴：可選項目符號(- / *) + 中括號狀態框；[x]/[X]=去過、[ ]/空=想去
_CHECKBOX_RE = re.compile(r"^\s*(?:[-*]\s*)?\[\s*([xX ]?)\s*\]\s*")
# 純項目符號(無勾選框)：- 店名 / * 店名
_BULLET_RE = re.compile(r"^\s*[-*]\s+")


def strip_checkbox(line: str) -> tuple[str, str]:
    """剝 markdown 待辦勾選框前綴,帶出狀態（純函式,可單測）。

    回 (status, content)：
      "- [ ] 鼎泰豐 (信義店)" → ("想去", "鼎泰豐 (信義店)")
      "- [x] 映客 (台中"      → ("去過", "映客 (台中")   # 尾端括號原樣保留給 codex
      "- 鼎泰豐"              → ("想去", "鼎泰豐")
      "海底撈"               → ("想去", "海底撈")
    [x]/[X]=去過,其餘=想去。尾端括號不動。
    """
    s = line or ""
    m = _CHECKBOX_RE.match(s)
    if m:
        status = "去過" if m.group(1).lower() == "x" else "想去"
        return status, s[m.end():].strip()
    # 沒勾選框 → 想去；若只是項目符號(- / *)也剝掉
    return "想去", _BULLET_RE.sub("", s).strip()


BATCH_LINE_CAP = 60  # 單則訊息批次上限；超過只處理前 60 行（spec §6.4）


def split_lines(text: str) -> list[str]:
    """切行、去空白行、每行 strip（純函式）。"""
    if not text:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def is_batch(text: str) -> bool:
    """非空行數 ≥ 2 → 批次（spec §5）。"""
    return len(split_lines(text)) >= 2


def take_capped(lines: list[str]) -> tuple[list[str], int]:
    """取前 BATCH_LINE_CAP 行；回 (kept, dropped)。dropped>0 時總結卡明講未處理數。"""
    kept = lines[:BATCH_LINE_CAP]
    dropped = max(0, len(lines) - BATCH_LINE_CAP)
    return kept, dropped
