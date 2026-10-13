"""Google Places API (New) 薄封裝。I/O 邊界。

**失敗要看得見**：Google 停用專案（例如免費試用到期）時每一發都 403，
若 log 沒有紀錄，故障只會出現在 Discord 的補件卡片上，很久都不會被發現。
所以這一層做兩件事：把 Google 的回應翻成人話印進 log（含連續失敗次數＝壞多久了），
並用 `PlacesUnavailable` 讓呼叫端分得出「服務掛了」與「Google 真的查無此店」。
"""
import os
import json
import urllib.request
import urllib.parse
import urllib.error

from food.regions import resolve_region
from app_secrets import get_secret

# Google API 呼叫計數（給 enrich.backfill_all 控預算用；Places API New 按次計費）
_api_calls = 0

# 連續失敗次數。印在 log 裡是為了回答「這到底壞多久了」——
# 單看一行 403 沒人知道是偶發還是已經死了三天。成功一次就歸零。
_failure_streak = 0


class PlacesUnavailable(RuntimeError):
    """Google Places 這次服務不可用（金鑰、專案、配額、網路都算）。

    刻意**不是**「查無此店」：後者是 Google 正常回答了「沒有」，
    前者是根本沒問到。兩者給使用者的建議完全相反。
    """

    def __init__(self, message: str, *, status: int | None = None,
                 reason: str | None = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.reason = reason
        # detail＝給維運看的完整診斷（進 log）。訊息本身要短，因為它會出現在
        # Discord 卡片上給兩個人看——「帳單失效」是維運的問題，不是使用者的待辦。
        self.detail = detail or message


# Google 的 ErrorInfo.reason → 人話。key 限制類的都會附 reason，專案層級的不會。
_REASON_HINTS = {
    "API_KEY_SERVICE_BLOCKED": "金鑰的 API 限制清單沒有勾這個服務",
    "API_KEY_HTTP_REFERRER_BLOCKED": "金鑰的 referer 限制擋下了這個請求",
    "API_KEY_IP_ADDRESS_BLOCKED": "金鑰的 IP 限制擋下了這個請求",
    "API_KEY_INVALID": "金鑰無效或已被刪除",
    "SERVICE_DISABLED": "這個 API 沒有在專案裡啟用",
    "RATE_LIMIT_EXCEEDED": "配額用完了",
    "RESOURCE_EXHAUSTED": "配額用完了",
    "BILLING_DISABLED": "專案的帳單沒有啟用",
}


def describe_api_error(status: int, body: str) -> tuple[str | None, str]:
    """把 Google 的錯誤回應翻成 (reason, 人話)。純函式，可單測。

    最重要的是**沒有 reason 的那一種**：金鑰通過了全部檢查、卻在服務層被拒，
    Google 只回一句 "The caller does not have permission"（例如試用到期），
    而它最容易把人騙去翻金鑰設定。
    """
    reason = None
    message = ""
    try:
        err = (json.loads(body) or {}).get("error") or {}
        message = err.get("message") or ""
        for d in err.get("details") or []:
            if d.get("reason"):
                reason = d["reason"]
                break
    except Exception:
        pass   # 非 JSON（攔截頁、HTML 錯誤頁）→ 下面用狀態碼講話

    if reason:
        return reason, f"{status} {reason}：{_REASON_HINTS.get(reason, message or '見 Google 回應')}"
    if status == 403:
        return None, ("403 專案層級被拒：多半是帳單失效／免費試用到期／服務未在專案啟用"
                      "——金鑰本身沒問題，別去翻金鑰設定")
    if status == 429:
        return None, "429 配額用完了"
    return None, f"{status} {message or 'Google 沒有說明原因'}"


def _log_failure(what: str, status: int | None, human: str) -> None:
    """統一的失敗 log。格式固定，方便之後 grep 或接告警。"""
    global _failure_streak
    _failure_streak += 1
    print(f"⚠️ Places {what} 失敗（連續第 {_failure_streak} 次）：{human}", flush=True)


def _note_success() -> None:
    global _failure_streak
    _failure_streak = 0


def reset_failure_streak() -> None:
    """測試用：把連續失敗計數歸零。"""
    _note_success()


def failure_streak() -> int:
    return _failure_streak


def _unavailable(what: str, exc: Exception) -> PlacesUnavailable:
    """把 urllib 的例外轉成帶語意的 PlacesUnavailable，並留下 log。"""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        reason, human = describe_api_error(exc.code, body)
        _log_failure(what, exc.code, human)
        return PlacesUnavailable(f"Google 服務暫時不可用（{exc.code}）",
                                 status=exc.code, reason=reason, detail=human)
    human = f"連不到 Google：{exc}"
    _log_failure(what, None, human)
    return PlacesUnavailable("Google 服務暫時不可用（連不到）", detail=human)


def _count(n: int = 1) -> None:
    global _api_calls
    _api_calls += n


def api_call_count() -> int:
    return _api_calls


_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.addressComponents"
)


def search_text(query: str) -> dict | None:
    """用文字查最相關的一家店。回正規化後的 dict，查無回 None。"""
    key = get_secret("GOOGLE_PLACES_SERVER_KEY")
    if not key:
        # 跟「被拒」歸同一類：呼叫端只需要接一種例外，也一樣要看得見
        _log_failure("查店家", None, "GOOGLE_PLACES_SERVER_KEY 未設定")
        raise PlacesUnavailable("Google 服務暫時不可用（未設定金鑰）",
                                detail="GOOGLE_PLACES_SERVER_KEY 未設定")
    _count()
    body = json.dumps(
        {"textQuery": query, "languageCode": "zh-TW", "maxResultCount": 1}
    ).encode("utf-8")
    req = urllib.request.Request(
        _SEARCH_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": _FIELD_MASK,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        raise _unavailable("查店家", ex) from None
    _note_success()
    places = data.get("places") or []
    if not places:
        return None
    p = places[0]
    if not p.get("id"):
        return None  # 沒有 place_id 無法去重/導航，視同查無
    # 台灣以地址文字為真相（Google 的行政區 component 時有時無），國外走 components
    region = resolve_region(p.get("formattedAddress"), p.get("addressComponents"))
    loc = p.get("location") or {}
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text"),
        "address": p.get("formattedAddress"),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "country": region["country"],
        "city": region["city"],
        "district": region["district"],
    }


def maps_url(place_id: str, name: str = "") -> str:
    """組 Google Maps 連結（官方 Maps URLs api=1 格式，導航/查看用）。

    query 為必填（place_id 找不到時的 fallback）；有店名就帶店名，否則用 place_id 字串墊。
    參考：https://developers.google.com/maps/documentation/urls/get-started
    """
    query = urllib.parse.quote(name or place_id)
    return (
        "https://www.google.com/maps/search/?api=1"
        f"&query={query}&query_place_id={place_id}"
    )


_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"


def fetch_reviews(place_id: str) -> list[dict]:
    """抓 Place Details 的 reviews 欄位（最相關約 5 則）。失敗回 []。"""
    key = get_secret("GOOGLE_PLACES_SERVER_KEY")
    if not key or not place_id:
        return []   # 沒 place_id 是正常情境（手動建的店），不算失敗
    try:
        _count()
        req = urllib.request.Request(
            _DETAILS_URL.format(place_id=place_id),
            method="GET",
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "reviews",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        _note_success()
        return data.get("reviews") or []
    except Exception as ex:
        # 事後加值失敗不該擋入庫，但不能靜悄悄
        _unavailable("抓評論", ex)
        return []


def caution_for_place_id(place_id: str) -> str:
    """用低星評論做雷點摘要。沒低星回友善訊息；任何失敗回空字串。"""
    from codex_cli import codex_text
    reviews = fetch_reviews(place_id)
    if not reviews:
        return ""
    low_lines: list[str] = []
    for r in reviews:
        rating = r.get("rating") or 0
        text = (r.get("text") or {}).get("text") or r.get("originalText", {}).get("text") or ""
        if rating and rating <= 3 and text:
            low_lines.append(f"({rating}星) {text}")
    if not low_lines:
        return "近期評論沒看到明顯雷點"
    prompt = (
        "以下是 Google 評論的低星留言，請用一句話(<=40字)歸納主要雷點，"
        "台灣口語、不加標題、不列點，直接給文字：\n\n"
        + "\n\n".join(low_lines[:5])
    )
    try:
        return codex_text(prompt).strip()[:200]
    except Exception:
        return ""


# 推薦菜的輸出形狀交給 codex --output-schema 保證；分隔符與「最多 5 樣」由程式負責。
_DISHES_SCHEMA = {
    "type": "object",
    "properties": {"dishes": {"type": "array", "items": {"type": "string"}}},
    "required": ["dishes"],
    "additionalProperties": False,
}


def recommended_for_place_id(place_id: str) -> str:
    """從評論萃取『大家推薦點什麼』。沒評論/沒提到餐點/失敗皆回空字串。"""
    from codex_cli import codex_text
    reviews = fetch_reviews(place_id)
    lines = []
    for r in reviews:
        text = (r.get("text") or {}).get("text") or (r.get("originalText") or {}).get("text") or ""
        if text:
            lines.append(text)
    if not lines:
        return ""
    prompt = (
        "以下是某餐廳的 Google 評論。請歸納『大家最常推薦點的餐點』，"
        "dishes 只放菜名、最常被推薦的排前面；評論裡沒提到任何具體餐點就給空陣列：\n\n"
        + "\n\n".join(lines[:5])
    )
    try:
        dishes = json.loads(codex_text(prompt, schema=_DISHES_SCHEMA))["dishes"]
        return "、".join([d.strip() for d in dishes if d.strip()][:5])[:200]
    except Exception:
        return ""


_PHOTO_MEDIA_URL = "https://places.googleapis.com/v1/{name}/media"


def fetch_place_photo(place_id: str, max_px: int = 800) -> tuple[bytes, str] | None:
    """抓該店第一張 Google 照片的 bytes。回 (data, 'jpg') 或 None。"""
    key = get_secret("GOOGLE_PLACES_SERVER_KEY")
    if not key or not place_id:
        return None
    try:
        # 1) 先拿 photo 的 resource name（field mask = photos）
        _count()
        req = urllib.request.Request(
            _DETAILS_URL.format(place_id=place_id), method="GET",
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": "photos"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        photos = data.get("photos") or []
        name = (photos[0].get("name") if photos else None)
        if not name:
            return None
        # 2) 下載實際照片 bytes（media endpoint 會轉址到真圖）
        _count()
        url = _PHOTO_MEDIA_URL.format(name=name) + \
            f"?maxHeightPx={max_px}&key={urllib.parse.quote(key)}"
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = {"image/jpeg": "jpg", "image/png": "png",
               "image/webp": "webp", "image/gif": "gif"}.get(ctype, "jpg")
        _note_success()
        return data, ext
    except Exception as ex:
        _unavailable("抓照片", ex)
        return None
