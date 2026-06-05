"""美食抽取 → Places → 入庫 → 事後雷點 的 orchestrator。

回傳 (place_dict_or_None, missing_reason)：
- place_dict_or_None 非 None 代表入庫成功，含 _created（True=新增 / False=更新既有）
- place_dict_or_None None 代表缺資訊或查不到，呼叫端應建 pending 卡

雷點摘要採事後加值（best-effort），失敗不影響入庫。
"""
import re
import asyncio
from food import extract
from food.links import classify_platform
from food.places import search_text, caution_for_place_id
from food.repo import upsert_place, update_caution, set_visited


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


def bucket_line(fields: dict, place: dict | None) -> str:
    """信心分桶（純函式,spec §6.2）。回 "ok" | "review" | "fail"。

    ✅ ok    ：codex 有 area 且 Google 回的店有 city 或 country
    ⚠️ review：有配對(place 非 None)但 codex 無 area 或 Google 無 city/country
    ❌ fail   ：codex 抽不到店名,或 Google 無配對(place 為 None)

    用 city 或 country 是為了國外店：country 一定填、city 有就填(spec 美食地圖 §4.1),
    國外只有 country 的店若 codex 也給了 area,仍算高信心。
    """
    name = (fields.get("name") or "").strip()
    if not name or place is None:
        return "fail"
    area = (fields.get("area") or "").strip()
    city = (place.get("city") or "").strip()
    country = (place.get("country") or "").strip()
    if area and (city or country):
        return "ok"
    return "review"


def dedupe_resolved(resolved: list[dict]) -> list[dict]:
    """依 place_id 程序內去重(保序),狀態只升級不降級（純函式,spec §6.1 修 TOCTOU）。

    resolved 每筆 = {bucket, place, fields, status, raw}（與 _resolve_one 回傳同形）。
    同一 place_id 只留第一筆;若任一筆 status=="去過" 則該店升級為去過。
    """
    by_place: dict[str, dict] = {}
    order: list[str] = []
    for r in resolved:
        pid = r["place"]["place_id"]
        cur = by_place.get(pid)
        if cur is None:
            by_place[pid] = dict(r)        # 淺拷貝,避免改到原物件
            order.append(pid)
        elif r["status"] == "去過":
            cur["status"] = "去過"          # 只升級不降級
    return [by_place[pid] for pid in order]


_BATCH_SEMAPHORE = 6  # 同時在飛的 Google 正名上限（net-new 限流,spec §6.4）


def _resolve_one(fields: dict, status: str, content: str) -> dict:
    """同步,在 thread 內跑：Google 正名 + 分桶判定。**不 upsert**（留到去重後統一寫）。

    回 {bucket, place, fields, status, raw}；bucket ∈ {"ok","review","fail"}。
    name 空 / Google 無配對 / 例外 → bucket="fail"、place=None。
    """
    name = (fields.get("name") or "").strip()
    if not name:
        return {"bucket": "fail", "place": None, "fields": fields,
                "status": status, "raw": content}
    query = f"{name} {fields.get('area') or ''}".strip()
    try:
        place = search_text(query)
    except Exception:
        place = None
    bucket = bucket_line(fields, place)
    return {"bucket": bucket, "place": place, "fields": fields,
            "status": status, "raw": content}


async def batch_from_text(blob: str) -> dict:
    """批次匯入 orchestrator（spec §6）。回 buckets dict 給 food_batch_summary_embed。

    回 {
      "total_lines": int,          # 取前 cap 後實際處理的非空行數
      "dropped": int,              # 超過 60 行未處理數（0=未截斷）
      "wishlist": int, "visited": int,   # 想去/去過計數（標題用）
      "ok": int,                   # ✅ 高信心家數（已入庫,預設只給計數）
      "review": list[dict],        # ⚠️ 需確認：[{id, raw_name, resolved_name}]
      "fail": list[str],           # ❌ 找不到：[原始該行文字]
      "error": str | None,         # 整批 codex 掛掉 → 一句訊息,其餘欄位空
    }
    """
    lines = split_lines(blob)
    kept, dropped = take_capped(lines)
    base = {"total_lines": len(kept), "dropped": dropped, "wishlist": 0,
            "visited": 0, "ok": 0, "review": [], "fail": [], "error": None}
    if not kept:
        return base

    # 0) 行正規化：剝勾選框、帶出狀態
    parsed = [strip_checkbox(ln) for ln in kept]      # list[(status, content)]
    statuses = [s for s, _ in parsed]
    contents = [c for _, c in parsed]
    base["wishlist"] = sum(1 for s in statuses if s == "想去")
    base["visited"] = sum(1 for s in statuses if s == "去過")

    # 1) 一次 codex 批解析（整批掛掉 → 整批回錯,不假裝成功,spec §8）
    try:
        fields_list = await asyncio.to_thread(extract.parse_place_list, contents)
    except Exception as ex:
        base["error"] = f"解析失敗：{ex}"
        return base

    # 2) 逐行 Google 正名（平行 + Semaphore 限流；限流只在 async 層）
    sem = asyncio.Semaphore(_BATCH_SEMAPHORE)

    async def _bounded(i):
        async with sem:
            return await asyncio.to_thread(
                _resolve_one, fields_list[i], statuses[i], contents[i]
            )

    results = await asyncio.gather(
        *[_bounded(i) for i in range(len(contents))], return_exceptions=True
    )

    # 3) 分流：fail 直接落桶；resolved 留待去重後統一 upsert（修 TOCTOU）
    resolved: list[dict] = []
    for content, res in zip(contents, results):
        if isinstance(res, Exception) or res is None:
            base["fail"].append(content)
            continue
        if res["bucket"] == "fail":
            base["fail"].append(res["raw"])
            continue
        resolved.append(res)

    # 3b) 程序內依 place_id 去重 + 狀態升級,再統一入庫
    for r in dedupe_resolved(resolved):
        place = r["place"]
        fields = r["fields"]
        try:
            p, _created = upsert_place(
                place,
                recommended_items=fields.get("recommended_items") or None,
                cuisine_type=fields.get("cuisine_type") or None,
            )
        except Exception:
            base["fail"].append(r["raw"])     # 真的沒入庫才算找不到
            continue
        if r["status"] == "去過":
            try:
                set_visited(p["id"])          # 複用既有;只升級成去過
            except Exception:
                pass                          # 已入庫,標去過失敗不改變「已入庫」事實
        if r["bucket"] == "ok":
            base["ok"] += 1
        else:
            base["review"].append({
                "id": p["id"],
                "raw_name": fields.get("name") or r["raw"],
                "resolved_name": place.get("name") or "",
            })
    return base
