# 美食地圖 Phase 3（連結來源）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 `#美食輸入` 貼 IG / YouTube / TikTok / Threads / Facebook / Google Maps / 一般網站連結 → bot 用 **yt-dlp(主)+ og fetch 爬蟲 UA(備援)** 抽出店家文字 → 餵既有 codex / Places pipeline → 自動入庫;**抽不到店名一律走 pending 補件**(reply 補店名很順);一則訊息含多個連結 → **平行處理一次多家入庫**。

**Architecture:** yt-dlp 為核心抽取器(社群維護、隨平台改版升級,我們不維護各平台爬蟲)。新增 `food/links.py`(URL 偵測 + 平台判斷,純函式可單測);擴充 `food/extract.py` 新增 `parse_video_id` / `gmaps_place_name` / `parse_og`(純函式)+ `from_url` I/O wrapper(內部按平台分流呼叫 yt-dlp / 自訂解析);新增 `food/ingest.py:from_url(url, caption)` 串接 → 復用既有 `extract.from_text`(codex)→ `_from_fields`(Places + 入庫 + 雷點)。`discord_handler._handle_food_message` 在純文字 ingest **之前** 插入「連結分流」區塊,多連結用 `asyncio.gather` 平行抽取。抽不到一律降級成 `food_missing_embed` + `pending.remember(source_url=url)`。

**Tech Stack:** Python 3.11、`yt-dlp`(新依賴,純 Python)、既有 codex_cli / Places / pending、discord.py、pytest。

> 對應 spec:`docs/superpowers/specs/2026-05-23-food-map-module-design.md` §6.5。
> **重要修正**:spec §6.5 原寫「不做 yt-dlp 下載影片+抽幀」是針對「下載影片本體+OCR」,但 **yt-dlp `--skip-download` 只抽 metadata(title/description/caption)是合法且輕量的用法**,跟「抽幀」完全不同。實測 IG reel 直接拿到完整 caption(店名/區域/推薦品項全在),這才是 Phase 3 的核心。
> 已確認決策:① 不留 cookie 口子(只靠公開貼文);② 多連結平行處理一次多家入庫;③ 抽不到走既有 `pending` 補件。
> 專案慣例:每次 commit 同步更新 `README.md` / `CODEBASE.md`(Task 9)。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `requirements.txt` | 修改 | 加 `yt-dlp` |
| `food/links.py` | 建立 | `find_urls()` / `classify_platform()` / `strip_urls()` / `detect_links()` / `first_link()`(全純函式) |
| `food/extract.py` | 修改 | 新增純函式 `parse_video_id()` / `gmaps_place_name()` / `parse_og()` + I/O wrapper `from_url(url, platform)` |
| `food/ingest.py` | 修改 | 新增 `from_url(url, *, caption='')`(orchestrator,復用 `_from_fields`) |
| `discord_handler.py` | 修改 | `_handle_food_message` 在純文字 ingest 前插入連結分流 + `asyncio.gather` 多連結平行 |
| `tests/test_food_links.py` | 建立 | links 模組純函式 TDD |
| `tests/test_food_extract.py` | 擴充 | `parse_video_id` / `gmaps_place_name` / `parse_og` 純函式 TDD |
| `README.md` / `CODEBASE.md` | 修改 | 文件 |

測試:`docker compose exec -T app pytest tests/ -v`
套用 .py 改動:`docker compose restart app`;requirements 改動需 `docker compose build app` 重 build。

---

## Task 1: 加 `yt-dlp` 依賴 + 重 build

**Files:** `requirements.txt`

- [ ] **Step 1:** 在 `requirements.txt` 末尾加一行(若已存在則略過):
```
yt-dlp
```

- [ ] **Step 2:** Rebuild 並啟動:
```bash
docker compose build app
docker compose up -d app
sleep 5
```

- [ ] **Step 3:** 驗證容器內 yt-dlp 可用 + 對 IG reel 真實抽取成功:
```bash
docker compose exec -T app python -c "
import yt_dlp, json
with yt_dlp.YoutubeDL({'quiet':True,'skip_download':True,'no_warnings':True}) as y:
    i = y.extract_info('https://www.instagram.com/reel/DYecU0BRIs9/', download=False)
print('title:', i.get('title')[:60])
print('caption 長度:', len(i.get('description') or ''))
assert '肉麻訣' in (i.get('description') or '') or len(i.get('description') or '') > 100, 'caption 抽不到'
print('OK')
"
```
Expected:印出 title、caption 長度 > 100、最後 `OK`。

- [ ] **Step 4:** Commit:
```bash
git add requirements.txt
git commit -m "feat(food): add yt-dlp dependency for link extraction"
```

---

## Task 2: `food/links.py` URL 偵測 + 平台判斷(純函式 TDD)

**Files:** `food/links.py`、`tests/test_food_links.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_food_links.py`:**
```python
from food.links import find_urls, classify_platform, strip_urls, detect_links, first_link


def test_find_urls_basic():
    assert find_urls("吃這家 https://www.instagram.com/reel/ABC/ 很讚") == ["https://www.instagram.com/reel/ABC/"]


def test_find_urls_multiple_dedup_preserve_order():
    txt = "https://youtu.be/x https://www.instagram.com/p/Y/ https://youtu.be/x"
    assert find_urls(txt) == ["https://youtu.be/x", "https://www.instagram.com/p/Y/"]


def test_find_urls_strips_chinese_punctuation():
    # 句尾全形句號 / 半形句點 / 全形右括號要剝掉
    assert find_urls("看這個 https://www.tiktok.com/@x/video/123。") == ["https://www.tiktok.com/@x/video/123"]
    assert find_urls("(來源 https://example.com/abc)") == ["https://example.com/abc"]


def test_find_urls_discord_angle_brackets():
    # Discord <url> 抑制預覽格式,要正確抓中間 URL
    assert find_urls("<https://www.youtube.com/watch?v=ABC>") == ["https://www.youtube.com/watch?v=ABC"]


def test_find_urls_empty():
    assert find_urls("") == []
    assert find_urls("沒有連結的文字") == []


def test_classify_platform_youtube():
    assert classify_platform("https://www.youtube.com/watch?v=ABC") == "youtube"
    assert classify_platform("https://youtu.be/ABC") == "youtube"
    assert classify_platform("https://www.youtube.com/shorts/XYZ") == "youtube"


def test_classify_platform_instagram():
    assert classify_platform("https://www.instagram.com/reel/ABC/") == "instagram"
    assert classify_platform("https://www.instagram.com/p/XYZ/") == "instagram"


def test_classify_platform_threads():
    assert classify_platform("https://www.threads.com/@x/post/ABC") == "threads"
    assert classify_platform("https://www.threads.net/@x/post/ABC") == "threads"


def test_classify_platform_tiktok():
    assert classify_platform("https://www.tiktok.com/@x/video/123") == "tiktok"
    assert classify_platform("https://vt.tiktok.com/abc/") == "tiktok"


def test_classify_platform_facebook():
    assert classify_platform("https://www.facebook.com/foo/posts/123") == "facebook"
    assert classify_platform("https://fb.watch/abc/") == "facebook"


def test_classify_platform_gmaps():
    assert classify_platform("https://www.google.com/maps/place/鼎泰豐") == "gmaps"
    assert classify_platform("https://maps.app.goo.gl/abc") == "gmaps"
    assert classify_platform("https://goo.gl/maps/abc") == "gmaps"


def test_classify_platform_phishing_subdomain():
    # 子網域邊界比對:youtube.com.evil.com 應判 other
    assert classify_platform("https://youtube.com.evil.com/abc") == "other"


def test_classify_platform_other():
    assert classify_platform("https://example.com/abc") == "other"


def test_strip_urls():
    assert strip_urls("吃這家 https://x.com 很讚") == "吃這家  很讚"
    assert strip_urls("https://x.com") == ""
    assert strip_urls("沒連結") == "沒連結"


def test_detect_links_returns_dicts():
    out = detect_links("看 https://www.youtube.com/watch?v=A 和 https://www.instagram.com/p/B/")
    assert out == [
        {"platform": "youtube", "url": "https://www.youtube.com/watch?v=A"},
        {"platform": "instagram", "url": "https://www.instagram.com/p/B/"},
    ]


def test_first_link_none_when_no_url():
    assert first_link("純文字") is None


def test_first_link_returns_first():
    assert first_link("https://youtu.be/A https://www.tiktok.com/@x/video/1") == {
        "platform": "youtube", "url": "https://youtu.be/A",
    }
```

- [ ] **Step 2:** 跑測試確認失敗:
```bash
docker compose exec -T app pytest tests/test_food_links.py -v
```
Expected:`ModuleNotFoundError: No module named 'food.links'`。

- [ ] **Step 3: 實作 `food/links.py`(純函式,stdlib only):**
```python
"""URL 偵測 + 平台判斷(純函式,無 I/O,可單測)。"""
import re
from urllib.parse import urlsplit

# 比對 http(s) URL,容許大部分 URL 合法字元(RFC 3986 子集)
_URL_RE = re.compile(r'https?://[^\s<>"　，。！？、）)】」』]+', re.IGNORECASE)
# 句尾標點(中英文,半全形)要剝掉
_TRAILING = '.,;:!?。，、！？)】」』 　'

# 平台 → 認可的網域(子網域邊界比對,防釣魚)
_HOST_RULES = {
    "youtube":   ["youtube.com", "youtu.be"],
    "instagram": ["instagram.com", "instagr.am"],
    "threads":   ["threads.com", "threads.net"],
    "tiktok":    ["tiktok.com"],
    "facebook":  ["facebook.com", "fb.com", "fb.watch", "m.facebook.com"],
    "gmaps":     ["google.com/maps", "maps.app.goo.gl", "goo.gl/maps", "maps.google.com"],
}


def find_urls(text: str) -> list[str]:
    """從文字抽出所有 http(s) URL,保序去重、剝句尾標點。"""
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(_TRAILING)
        if url and url not in seen:
            seen[url] = None
    return list(seen.keys())


def classify_platform(url: str) -> str:
    """判斷 URL 屬於哪個平台。host 用子網域邊界比對防釣魚。"""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = (parts.path or "")
    except Exception:
        return "other"
    if not host:
        return "other"
    # gmaps 需要 host+path 一起看(google.com/maps、goo.gl/maps)
    full = host + path
    for plat, hosts in _HOST_RULES.items():
        for h in hosts:
            if "/" in h:
                # 含路徑:整段比對(host+path 開頭)
                if full.startswith(h) or full.startswith("www." + h):
                    return plat
            else:
                # 純 host:邊界比對(完全相等或子網域)
                if host == h or host.endswith("." + h):
                    return plat
    return "other"


def strip_urls(text: str) -> str:
    """移除文字中的 URL,留下使用者註解。"""
    if not text:
        return ""
    return _URL_RE.sub("", text).strip(" \t\n") if _URL_RE.sub("", text).strip() else ""


def detect_links(text: str) -> list[dict]:
    """偵測所有連結 → list of {platform, url}。"""
    return [{"platform": classify_platform(u), "url": u} for u in find_urls(text)]


def first_link(text: str) -> dict | None:
    """取第一個連結,沒有回 None。"""
    links = detect_links(text)
    return links[0] if links else None
```

- [ ] **Step 4:** 跑測試確認通過:
```bash
docker compose exec -T app pytest tests/test_food_links.py -v
```
Expected:全部 passed(約 17 項)。

- [ ] **Step 5:** Commit:
```bash
git add food/links.py tests/test_food_links.py
git commit -m "feat(food): URL detection + platform classification (pure)"
```

---

## Task 3: `parse_video_id`(YouTube 影片 ID 解析,純函式 TDD)

**Files:** `food/extract.py`、`tests/test_food_extract.py`

> 用於 yt-dlp 失敗時的備用識別(或日後切換 oEmbed)。

- [ ] **Step 1: 擴充 `tests/test_food_extract.py` 末尾加:**
```python
from food.extract import parse_video_id


def test_parse_video_id_watch():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_video_id_youtu_be():
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ?si=xxx") == "dQw4w9WgXcQ"


def test_parse_video_id_shorts():
    assert parse_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_video_id_embed():
    assert parse_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_video_id_with_extra_params():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s") == "dQw4w9WgXcQ"


def test_parse_video_id_not_youtube():
    assert parse_video_id("https://example.com/abc") is None
    assert parse_video_id("https://www.instagram.com/reel/ABC/") is None
```

- [ ] **Step 2:** 跑測試確認失敗(ImportError on `parse_video_id`)。

- [ ] **Step 3: 在 `food/extract.py` 末尾加:**
```python
import re as _re

_YT_ID_RE = _re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|v/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def parse_video_id(url: str) -> str | None:
    """從 YouTube URL 解出 11 碼 video id;非 YouTube 或解不出回 None。"""
    if not url:
        return None
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None
```

- [ ] **Step 4:** 跑測試確認通過(6 項)。

- [ ] **Step 5:** Commit:
```bash
git add food/extract.py tests/test_food_extract.py
git commit -m "feat(food): parse_video_id for YouTube URLs (pure)"
```

---

## Task 4: `gmaps_place_name`(Google Maps URL path 解店名,純函式 TDD)

**Files:** `food/extract.py`、`tests/test_food_extract.py`

> Google Maps 連結最穩、免 AI 的路線:從 URL `/maps/place/<name>` 直接解店名。短連結(`maps.app.goo.gl`)需 follow redirect 後再丟此函式。redirect 是 I/O,放在 Task 6 的 `from_url`。

- [ ] **Step 1: 擴充測試:**
```python
from food.extract import gmaps_place_name


def test_gmaps_chinese_place():
    url = "https://www.google.com/maps/place/鼎泰豐+信義店/@25.033,121.530,17z/data=!3m1"
    assert gmaps_place_name(url) == "鼎泰豐 信義店"


def test_gmaps_url_encoded():
    url = "https://www.google.com/maps/place/%E9%BC%8E%E6%B3%B0%E8%B1%90/@25,121,15z"
    assert gmaps_place_name(url) == "鼎泰豐"


def test_gmaps_english():
    url = "https://www.google.com/maps/place/Din+Tai+Fung/@25,121,15z"
    assert gmaps_place_name(url) == "Din Tai Fung"


def test_gmaps_coords_only():
    # 沒有 /place/<name>/ 段(只有座標)應回空字串
    assert gmaps_place_name("https://www.google.com/maps/@25.033,121.530,17z") == ""


def test_gmaps_not_maps_url():
    assert gmaps_place_name("https://example.com/abc") == ""
```

- [ ] **Step 2:** 跑測試確認失敗。

- [ ] **Step 3: 在 `food/extract.py` 加:**
```python
from urllib.parse import unquote_plus as _unquote_plus

_GMAPS_PLACE_RE = _re.compile(r"/maps/place/([^/@?]+)")


def gmaps_place_name(url: str) -> str:
    """從 Google Maps URL 解出店名;解不出回空字串。"""
    if not url:
        return ""
    m = _GMAPS_PLACE_RE.search(url)
    if not m:
        return ""
    return _unquote_plus(m.group(1)).strip()
```

- [ ] **Step 4:** 跑測試確認通過(5 項)。

- [ ] **Step 5:** Commit:
```bash
git add food/extract.py tests/test_food_extract.py
git commit -m "feat(food): gmaps_place_name URL path parser (pure)"
```

---

## Task 5: `parse_og`(HTML body → og:title/og:description,純函式 TDD)

**Files:** `food/extract.py`、`tests/test_food_extract.py`

- [ ] **Step 1: 擴充測試:**
```python
from food.extract import parse_og


def test_parse_og_basic():
    html = '<meta property="og:title" content="某店家 - 美食媒體"><meta property="og:description" content="台北信義區">'
    assert parse_og(html) == {"title": "某店家 - 美食媒體", "description": "台北信義區"}


def test_parse_og_attribute_order_swapped():
    # content 在前、property 在後
    html = '<meta content="X" property="og:title">'
    assert parse_og(html)["title"] == "X"


def test_parse_og_html_entity_decode():
    html = '<meta property="og:title" content="Tom &amp; Jerry">'
    assert parse_og(html)["title"] == "Tom & Jerry"


def test_parse_og_missing_returns_empty():
    assert parse_og("<html></html>") == {"title": "", "description": ""}


def test_parse_og_truncates_long():
    long = "X" * 5000
    html = f'<meta property="og:description" content="{long}">'
    out = parse_og(html)
    assert len(out["description"]) <= 2000  # 截斷上限
```

- [ ] **Step 2:** 跑測試確認失敗。

- [ ] **Step 3: 在 `food/extract.py` 加:**
```python
import html as _html

_OG_RE_TITLE = _re.compile(
    r'<meta[^>]+(?:'
    r'property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']'
    r'|content=["\']([^"\']*)["\'][^>]+property=["\']og:title["\']'
    r')',
    _re.IGNORECASE,
)
_OG_RE_DESC = _re.compile(
    r'<meta[^>]+(?:'
    r'property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']'
    r'|content=["\']([^"\']*)["\'][^>]+property=["\']og:description["\']'
    r')',
    _re.IGNORECASE,
)
_OG_MAX = 2000


def _og_first(html_body: str, regex) -> str:
    m = regex.search(html_body or "")
    if not m:
        return ""
    raw = next((g for g in m.groups() if g), "")
    return _html.unescape(raw)[:_OG_MAX]


def parse_og(html_body: str) -> dict:
    """從 HTML body 抽 og:title 與 og:description;沒有回空字串。"""
    return {
        "title": _og_first(html_body, _OG_RE_TITLE),
        "description": _og_first(html_body, _OG_RE_DESC),
    }
```

- [ ] **Step 4:** 跑測試確認通過(5 項)。

- [ ] **Step 5:** Commit:
```bash
git add food/extract.py tests/test_food_extract.py
git commit -m "feat(food): parse_og HTML meta extractor (pure)"
```

---

## Task 6: `extract.from_url`(I/O wrapper,手動驗證)

**Files:** `food/extract.py`

> 按 platform 分流:yt-dlp(YouTube/IG/TikTok/FB)、Maps follow redirect、其他網站走 og fetch。**所有失敗都回 `None`(代表降級)**,不 raise。

- [ ] **Step 1: 在 `food/extract.py` 末尾加(import 寫在現有 import 區):**

先在檔案頂部 import 區補上(若無):
```python
import urllib.request
import urllib.parse
```

然後在末尾加:
```python
_FETCH_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"  # Meta 平台對爬蟲 UA 才回 og meta;一般網站也接受。實測 Threads 用瀏覽器 UA 拿不到、用 facebookexternalhit 拿得到 og:description
_FETCH_TIMEOUT = 12
_FETCH_MAX_BYTES = 400_000


def _yt_dlp_blob(url: str) -> str | None:
    """用 yt-dlp 抽 title + description。失敗回 None。"""
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True}) as y:
            info = y.extract_info(url, download=False)
        title = (info.get("title") or "").strip()
        desc = (info.get("description") or "").strip()
        uploader = (info.get("uploader") or "").strip()
        parts = [p for p in (title, uploader, desc) if p]
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def _http_get(url: str) -> tuple[str, str] | None:
    """fetch URL → (final_url, body)。失敗回 None。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _FETCH_UA,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        })
        r = urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT)
        body = r.read(_FETCH_MAX_BYTES).decode("utf-8", "ignore")
        return r.geturl(), body
    except Exception:
        return None


def from_url(url: str, platform: str) -> str | None:
    """從連結抽『要餵 codex 的文字 blob』。失敗回 None 代表降級。

    - youtube / instagram / tiktok / facebook → 先試 yt-dlp,失敗退 og fetch
    - threads → og fetch(yt-dlp 不支援,但爬蟲 UA 拿得到 og:description)
    - gmaps → follow redirect → gmaps_place_name
    - other → og:title + og:description
    """
    if not url:
        return None

    if platform == "gmaps":
        got = _http_get(url)
        if not got:
            return None
        final_url, _ = got
        name = gmaps_place_name(final_url) or gmaps_place_name(url)
        return name or None

    # 主力:yt-dlp(YouTube/IG/TikTok/FB 的 caption 通常最完整)
    if platform in ("youtube", "instagram", "tiktok", "facebook"):
        blob = _yt_dlp_blob(url)
        if blob:
            return blob
        # 退到 og fetch(yt-dlp 失敗時)

    # og fetch(Threads / FB/IG/TikTok 退路 / 一般網站)
    got = _http_get(url)
    if not got:
        return None
    _, body = got
    og = parse_og(body)
    parts = [og.get("title", ""), og.get("description", "")]
    blob = "\n".join(p for p in parts if p)
    return blob or None
```

- [ ] **Step 2:** 重啟並對 4 種平台手動驗證:
```bash
docker compose restart app
docker compose exec -T app python -c "
from food.extract import from_url
print('YouTube  :', repr((from_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'youtube') or '(None)')[:80]))
print('IG reel  :', repr((from_url('https://www.instagram.com/reel/DYecU0BRIs9/', 'instagram') or '(None)')[:80]))
print('Threads  :', repr((from_url('https://www.threads.com/@lin_chen1027/post/DYcQJGbAUeb', 'threads') or '(None)')[:120]))
print('Gmaps    :', repr((from_url('https://www.google.com/maps/place/鼎泰豐+信義店/@25,121,15z', 'gmaps') or '(None)')[:80]))
"
```
Expected:
- YouTube 印出含 "Rick Astley" 或標題的字串(80 字截斷)
- IG 印出含 "肉麻訣" 或 caption 開頭
- Threads 印含「龍潭」「台式餐館」等文字(實測 og:description 抽得到,只是常缺店名)
- Gmaps 印 "鼎泰豐 信義店"

任一非預期結果先檢查再 commit。

- [ ] **Step 3:** Commit:
```bash
git add food/extract.py
git commit -m "feat(food): extract.from_url with yt-dlp + og/gmaps fallback"
```

---

## Task 7: `ingest.from_url`(orchestrator,手動驗證)

**Files:** `food/ingest.py`

- [ ] **Step 1: 在 `food/ingest.py` 末尾加:**
```python
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
```

- [ ] **Step 2:** 重啟 + 端到端驗證(IG reel → 完整入庫):
```bash
docker compose restart app
docker compose exec -T app python -c "
from food.ingest import from_url
p, missing = from_url('https://www.instagram.com/reel/DYecU0BRIs9/')
print('p:', None if p is None else (p['name'], p.get('city'), p['_created']))
print('missing:', missing or '(無)')
"
```
Expected:`p: ('肉麻訣 -中壢中原店', '桃園', True)`、`missing: (無)`。

- [ ] **Step 3:** 清掉測試資料:
```bash
docker compose exec -T app python -c "from database import SessionLocal; from models import FoodPlace; db=SessionLocal(); db.query(FoodPlace).delete(); db.commit(); db.close(); print('cleared')"
```

- [ ] **Step 4:** Commit:
```bash
git add food/ingest.py
git commit -m "feat(food): ingest.from_url orchestrator (extract → places → upsert)"
```

---

## Task 7B: `deep_extract_via_codex`(加碼第 3 層,純文字抽不到店名才用)

**Files:** `food/extract.py`

> **何時用**:`ingest.from_url` 走完 yt-dlp + og fetch + codex_text 後,`name` 仍為空(常見於 Threads/FB:店名只在招牌圖裡)。動用 codex full-access 看圖 + 搜尋交叉驗證。
> **代價誠實列**:延遲 30-90 秒;`danger-full-access` 等於放開沙箱(但容器內 ephemeral session、跑完就忘,爆炸半徑在容器內)。
> **守則**:設 timeout、ephemeral、不留 session、解析失敗 silent 回 None(不破壞主流程)。

- [ ] **Step 1: 在 `food/extract.py` 末尾加:**
```python
import json as _json
import subprocess as _subprocess
import tempfile as _tempfile

_DEEP_TIMEOUT = 120  # 上限
_DEEP_PROMPT = """任務:從這個美食社群連結抽出店家資訊。
連結: {url}
{hint_line}
請用任何方式取得內容並判斷(curl/python/yt-dlp/看圖辨識招牌/Google 搜尋交叉驗證)。
特別注意:店名常常在影片畫面/招牌圖片裡,文字描述可能只有地區/心得。

請只回 JSON,不要其他文字、不要 markdown 標籤:
{{"name":"店名","area":"地區/縣市","recommended_items":"推薦品項","cuisine_type":"料理類型"}}

任一欄位真的拿不到就空字串。整個都拿不到回所有欄位空字串的 JSON。"""


def deep_extract_via_codex(url: str, *, hint: str = "") -> dict | None:
    """codex full-access 看圖 + 搜尋深度振查。失敗回 None。"""
    if not url:
        return None
    hint_line = f"使用者額外提示: {hint}\n" if hint.strip() else ""
    prompt = _DEEP_PROMPT.format(url=url, hint_line=hint_line)
    fd, out_path = _tempfile.mkstemp(suffix=".json")
    import os as _os
    _os.close(fd)
    try:
        cmd = [
            "codex", "exec",
            "--ephemeral", "--skip-git-repo-check",
            "-s", "danger-full-access",
            "-C", "/tmp",
            "-o", out_path,
            "-",
        ]
        proc = _subprocess.run(
            cmd, input=prompt, text=True,
            capture_output=True, timeout=_DEEP_TIMEOUT,
        )
        if proc.returncode != 0:
            return None
        with open(out_path, encoding="utf-8") as f:
            raw = f.read().strip()
        # 去掉可能的 markdown 包覆
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        data = _json.loads(raw.strip())
        return {
            "name": (data.get("name") or "").strip(),
            "area": (data.get("area") or "").strip(),
            "recommended_items": (data.get("recommended_items") or "").strip(),
            "cuisine_type": (data.get("cuisine_type") or "").strip(),
        }
    except Exception:
        return None
    finally:
        try:
            _os.remove(out_path)
        except OSError:
            pass
```

- [ ] **Step 2: 用 Threads 真實連結手動驗證(預期 60-90 秒):**
```bash
docker compose restart app
docker compose exec -T app python -c "
from food.extract import deep_extract_via_codex
out = deep_extract_via_codex('https://www.threads.com/@lin_chen1027/post/DYcQJGbAUeb')
print(out)
"
```
Expected:回 dict,`name` 含店名(實測「許許台菜食坊」或近似),`area` 含「龍潭」。**若 codex 抽不到也只回 dict + 全空字串**,不應 raise。

- [ ] **Step 3: 端到端驗證 ingest.from_url 對 Threads 完整跑通(包含 fallback):**
```bash
docker compose exec -T app python -c "
from food.ingest import from_url
p, missing = from_url('https://www.threads.com/@lin_chen1027/post/DYcQJGbAUeb')
print('p:', None if p is None else (p['name'], p.get('city')))
print('missing:', missing or '(無)')
"
```
Expected:`p` 非 None、name 含店名、city 大概是「桃園」(龍潭屬桃園市)。若深度振查失敗則 `p` 為 None + `missing='threads 連結抽不到店名'`(走 pending,這也是合理結果)。

- [ ] **Step 4: 清測試資料:**
```bash
docker compose exec -T app python -c "from database import SessionLocal; from models import FoodPlace; db=SessionLocal(); db.query(FoodPlace).delete(); db.commit(); db.close(); print('cleared')"
```

- [ ] **Step 5: Commit:**
```bash
git add food/extract.py food/ingest.py
git commit -m "feat(food): deep_extract_via_codex fallback (full-access, vision+search)"
```

---

## Task 8: discord 連結分流(_handle_food_message 整合 + 多連結 asyncio.gather)

**Files:** `discord_handler.py`

> **關鍵**:插在「reply 補件 → 圖片 ingest」**之後**、「純文字 ingest」**之前**。`first_link` 為 None 時行為與舊路徑完全一致(零回歸)。

- [ ] **Step 1:** 找到 `_handle_food_message` 內「純文字 ingest」區塊起點(`if message.content and message.content.strip():` 那段),在它**之前**插入連結分流區塊。

完整新區塊(直接在純文字 if 之前貼):
```python
        # 連結 ingest(YouTube / IG / TikTok / Google Maps / 一般網站)
        from food.links import detect_links, strip_urls
        from food import ingest
        from food.repo import set_message_id
        links = detect_links(message.content or "")
        if links:
            caption = strip_urls(message.content or "")
            async with message.channel.typing():
                # 多連結平行抽取(asyncio.gather + to_thread)
                results = await asyncio.gather(
                    *[asyncio.to_thread(ingest.from_url, lk["url"], caption=caption) for lk in links],
                    return_exceptions=True,
                )
            # 一個連結→一張結果卡
            for lk, res in zip(links, results):
                url = lk["url"]
                platform = lk["platform"]
                if isinstance(res, Exception):
                    p, missing = None, f"處理失敗:{res}"
                else:
                    p, missing = res
                if p:
                    sent = await message.channel.send(
                        embed=food_place_embed(p, created=p.get("_created", True))
                    )
                    set_message_id(p["id"], sent.id)
                else:
                    hint = ""
                    if platform in ("threads", "facebook"):
                        hint = "貼文文字常只說地區、店名在圖裡 — reply 補上店名最快"
                    sent = await message.channel.send(embed=food_missing_embed(missing, hint=hint))
                    from food import pending
                    pending.remember(
                        sent.id,
                        original_message_id=message.id,
                        raw_text=caption,
                        source_url=url,
                        missing_reason=missing,
                    )
            return
```

> 注意:`asyncio` 已在 `discord_handler.py` 頂部 import,不用再 import。

- [ ] **Step 2:** 重啟 + 確認 import 沒壞、bot 連線:
```bash
docker compose restart app
sleep 3
docker compose exec -T app python -c "import discord_handler; print('import ok')"
docker compose logs app --tail=8 | grep -E "已上線|Traceback" || true
```
Expected:`import ok` + 看到「🐉 Discord Bot 已上線」、無 Traceback。

- [ ] **Step 3: 全測試確認無回歸:**
```bash
docker compose exec -T app pytest tests/ -q
```
Expected:全綠(原 76 + Task 2 約 17 + Task 3 約 6 + Task 4 約 5 + Task 5 約 5 ≈ **109 passed**)。

- [ ] **Step 4:** Commit:
```bash
git add discord_handler.py
git commit -m "feat(food): on_message link routing + asyncio.gather multi-link"
```

---

## Task 9: 文件 + Live 驗收

**Files:** `README.md`、`CODEBASE.md`

- [ ] **Step 1: README** 「美食地圖」段落加:
> - **貼連結自動記**(Phase 3):在 `#美食輸入` 貼 IG/YouTube/TikTok/Threads/Facebook/Google Maps/一般網站連結 → bot 用 yt-dlp(主)+ og fetch 爬蟲 UA(備援)抽出 caption/描述 → 自動入庫並貼卡片;一則訊息含多個連結 → 平行處理一次多家入庫;抽不到店名(常見於 Threads/FB:店名在圖不在文字)→ 走 ⚠️ 補件卡(reply 補店名最快)

- [ ] **Step 2: CODEBASE** File Map 加 `food/links.py`(URL 偵測 + 平台判斷,純函式);`food/extract.py` 條目補 `from_url` / `parse_video_id` / `gmaps_place_name` / `parse_og`(注意 og fetch 用 `facebookexternalhit` UA);`food/ingest.py` 條目補 `from_url`;「規劃中模組」美食地圖條目標記「Phase 1A + 1B + 2 + 3 已實作」並補 Phase 3 描述(yt-dlp 主力 + og 爬蟲 UA 備援、Threads 可抽 description、多連結 asyncio.gather 平行入庫、抽不到店名走 pending 補件)。

- [ ] **Step 3:** Commit:
```bash
git add README.md CODEBASE.md
git commit -m "docs(food): Phase 3 link sources (yt-dlp, multi-link gather)"
```

- [ ] **Step 4: Live 驗收(你親自做)** —— 在 `#美食輸入`:
1. 貼一條真實 IG reel → 應自動跳出店家卡(藍 pin 想去 + 連結存進 source_url)
2. 貼一條 YouTube 連結(描述含店名)→ 應自動跳卡
3. 一則訊息貼**多條連結** → 應跳出多張卡(平行處理)
4. 貼 Threads 連結 → 應抽到 og:description(含地區/心得),codex 若抽到店名直接跳卡;若沒抽到店名 → 跳 ⚠️ 補件卡,reply 補店名 → 自動接回正式卡
5. 貼純文字「鼎泰豐 信義」(沒連結)→ 仍走原本純文字 ingest 路徑(無回歸)
6. 貼純圖片 → 仍走原本圖片 ingest 路徑(無回歸)
7. 貼一條已存在的店連結 → 應回「已更新(這家記過了)」,不重複

---

## 完成標準

- [ ] `pytest tests/` 全綠(~109 passed)
- [ ] 容器內 yt-dlp 可用、IG reel 真實抽取成功
- [ ] Live 驗收 7 項全過
- [ ] 既有功能無回歸(純文字 / 純圖片 / reply 補件 / ✅ 反應 / slash 指令 / 地圖)

通過後進 `superpowers:finishing-a-development-branch` 合併。
