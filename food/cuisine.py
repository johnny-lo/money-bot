"""料理兩層分類：大類（12 選 1）+ 細類（自由文字）。純函式，無 I/O。

**12 大類的詞彙表只住在這裡**（spec D7）。不寫進 food/extract.py 的 LLM prompt：
兩份詞彙表必然漂移，且幻覺值會直接進 DB。prompt 繼續產自由文字，
大類一律由 classify() 推導 —— 規則改良後重跑回填就整批重新分類。

## 三層優先序

  A 店型（咖啡甜點 / 飲料冰品）> B 菜系國別 > C 弱品類（火鍋 / 燒烤 / 早午餐 / 酒吧）

- 「日式燒肉」→ 日式：B 勝 C。你去的是日式店，不是「燒烤」這個品類。（使用者定案）
- 「法式甜點」→ 咖啡甜點：A 勝 B。你去甜點店是為了甜點，不是為了法國。（使用者定案）

**分層只在判讀 cuisine_type 時套用**（它描述「這是什麼店」）。
判讀店名／推薦菜時純看最左命中（它們描述「賣什麼菜」）——
否則任何在推薦菜裡提到一塊蛋糕的餐廳都會被歸成咖啡甜點店。
"""
from food.regions import to_traditional

MAJORS: tuple[str, ...] = (
    "日式", "韓式", "中式", "台式", "東南亞", "西式",
    "火鍋", "燒烤", "早午餐", "咖啡甜點", "飲料冰品", "酒吧餐酒館",
)

# 這些詞出現在 cuisine_type 裡等於沒說（真實資料裡有 5 筆）→ 從細類剔除，
# 且整格都是這種詞時視同空白、退到店名判讀。
_JUNK: frozenset[str] = frozenset({
    "小館", "食堂", "餐廳", "餐館", "料理", "家常料理", "美食",
    "小吃店", "專賣店", "專門店", "店", "簡餐", "餐飲",
})

# 異體字：_S2T（簡→繁）沒收的餐飲用字
_VARIANTS = str.maketrans({"喱": "哩", "麪": "麵"})

# 分隔符 → 統一成頓號再切
_SEPARATORS = "，,、/／|｜・･ \t　"

# ── A 店型：勝過菜系國別 ──────────────────────────────────────
_SHOP_TYPE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("咖啡甜點", (
        "咖啡", "cafe", "café", "甜點", "甜品", "蛋糕", "麵包", "烘焙",
        "鬆餅", "下午茶", "舒芙蕾", "可頌", "布丁", "銅鑼燒", "泡芙",
        "甜甜圈", "司康", "貝果", "塔派", "馬卡龍", "蛋糕捲",
    )),
    ("飲料冰品", (
        "飲料", "手搖", "奶茶", "果汁", "冰淇淋", "刨冰", "冰品",
        "雪花冰", "冰店", "茶飲", "豆漿", "霜淇淋", "聖代", "氣泡飲",
    )),
)

# ── B 菜系國別：勝過弱品類 ────────────────────────────────────
# 所有關鍵字一律 ≥2 字：單字「日」「韓」「泰」會在店名裡亂命中（例：日日排骨）。
_NATION: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("日式", (
        "日式", "日本", "和食", "洋食", "日料", "居酒", "拉麵", "壽司",
        "丼飯", "海鮮丼", "生魚片", "刺身", "天婦羅", "烏龍麵", "蕎麥",
        "鰻魚", "燒鳥", "大阪燒", "廣島燒", "關東煮", "定食", "豚骨",
        "唐揚", "豬排", "親子丼", "壽喜燒", "和牛",
    )),
    ("韓式", (
        "韓式", "韓國", "韓料", "部隊鍋", "石鍋", "韓式炸雞", "辣炒年糕",
        "血腸", "泡菜鍋",
    )),
    ("中式", (
        "中式", "中華", "中國", "川菜", "川味", "重慶", "四川", "港式",
        "冰室", "茶餐廳", "上海", "江浙", "北方", "小籠包", "煎餅果子",
        "炒飯", "蒙古", "水餃", "鍋貼", "湘菜", "雲南", "燒臘", "粵菜",
        "麻辣燙", "刀削麵",
    )),
    ("台式", (
        "台式", "台灣", "小吃", "滷肉飯", "魯肉飯", "雞肉飯", "牛肉麵",
        "豆花", "鹽酥雞", "臭豆腐", "大腸麵線", "麵線", "肉圓", "板條",
        "粄條", "客家", "擔仔", "虱目魚", "便當", "自助餐", "豬腳",
        "割包", "雞排", "蚵仔", "米糕", "肉羹", "羊肉爐", "薑母鴨",
        "古早味", "仙草", "碗粿", "筒仔米糕", "當歸",
    )),
    ("東南亞", (
        "泰式", "泰國", "越南", "越式", "馬來", "新加坡", "印尼", "南洋",
        "叻沙", "河粉", "印度", "咖哩", "打拋", "月亮蝦餅", "娘惹",
    )),
    ("西式", (
        "西式", "西餐", "美式", "義式", "義大利", "法式", "法國", "西班牙",
        "德式", "墨西哥", "漢堡", "披薩", "pizza", "牛排", "義麵", "pasta",
        "三明治", "bbq", "歐式", "地中海", "希臘", "土耳其", "可麗餅",
        "燉飯", "帕尼尼", "沙拉吧", "排餐",
    )),
)

# ── C 弱品類：沒有國別線索時才落這裡 ──────────────────────────
_CATEGORY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("火鍋", ("火鍋", "鍋物", "涮涮鍋", "麻辣鍋", "酸菜白肉", "小火鍋", "鴛鴦鍋")),
    ("燒烤", ("燒烤", "燒肉", "烤肉", "串燒", "串烤", "碳烤", "炭烤", "鐵板燒", "烤物")),
    ("早午餐", ("早午餐", "brunch", "早餐", "蛋餅", "吐司")),
    ("酒吧餐酒館", ("餐酒館", "酒吧", "bistro", "小酒館", "清吧", "調酒", "居酒屋")),
)

# 大類別名（LLM／人手可能寫的近義詞）→ 正名。normalize_major 專用。
_MAJOR_ALIASES: dict[str, str] = {
    "日本料理": "日式", "日本菜": "日式", "和食": "日式",
    "韓國料理": "韓式", "韓國菜": "韓式",
    "中華料理": "中式", "中國菜": "中式", "中餐": "中式",
    "台灣料理": "台式", "台菜": "台式",
    "東南亞料理": "東南亞", "南洋料理": "東南亞",
    "西餐": "西式", "西洋料理": "西式", "美式": "西式",
    "義式": "西式", "法式": "西式",
    "鍋物": "火鍋", "燒肉": "燒烤", "烤肉": "燒烤",
    "咖啡": "咖啡甜點", "甜點": "咖啡甜點", "甜品": "咖啡甜點",
    "飲料": "飲料冰品", "冰品": "飲料冰品",
    "酒吧": "酒吧餐酒館", "餐酒館": "酒吧餐酒館",
}


def normalize_major(s: str | None) -> str:
    """→ 12 大類之一，否則空字串。

    這是**持久化邊界的守門員**：不管上游（LLM、人手、舊資料）給什麼，
    越界值都在這裡被清成空字串，結構性寫不進 DB。
    """
    key = to_traditional(s or "").translate(_VARIANTS).strip()
    if key in MAJORS:
        return key
    return _MAJOR_ALIASES.get(key, "")


def _prepare(s: str | None) -> tuple[str, str]:
    """→ (比對用字串, 顯示用字串)。

    折字（簡→繁、異體）與轉小寫都是逐字 1:1 對應，所以兩個字串的索引對得起來，
    可以用比對字串的索引去切顯示字串 —— 細類才不會被降成小寫。
    """
    display = to_traditional(s or "").translate(_VARIANTS).strip()
    return display.lower(), display


def _first_hit(text: str, tables) -> tuple[int, str, str] | None:
    """在 text 裡找最左命中的關鍵字 → (位置, 關鍵字, 大類)。同位取較長者。"""
    best = None
    for major, keywords in tables:
        for kw in keywords:
            i = text.find(kw)
            if i < 0:
                continue
            key = (i, -len(kw))
            if best is None or key < best[0]:
                best = (key, kw, major)
    if best is None:
        return None
    (idx, _), kw, major = best
    return idx, kw, major


def _clean_minor(display: str) -> str:
    """細類清洗：切 token、丟掉沒有資訊的詞、還原成頓號串。"""
    text = display
    for sep in _SEPARATORS:
        text = text.replace(sep, "、")
    tokens = [t for t in text.split("、") if t and t not in _JUNK]
    return "、".join(tokens)


def classify(raw: str | None, *, name: str = "", items: str = "") -> tuple[str, str]:
    """自由文字 → (大類, 細類)。判不出的部分回空字串（spec D6：不設「其他」桶）。

    先看 cuisine_type（描述店），套 A>B>C 分層；
    它沒訊號才看店名＋推薦菜（描述菜），純最左命中、且細類只放命中的關鍵字，
    不把整串菜單塞進細類。
    """
    match_raw, display_raw = _prepare(raw)
    minor = _clean_minor(display_raw)

    if minor:
        for tables in (_SHOP_TYPE, _NATION, _CATEGORY):
            hit = _first_hit(match_raw, tables)
            if hit is None:
                continue
            idx, kw, major = hit
            # 大類判自「◯式」國別詞且它就在開頭 → 細類不重複它（日式燒肉 → 日式 + 燒肉）
            if tables is _NATION and idx == 0 and kw.endswith("式"):
                minor = _clean_minor(display_raw[len(kw):])
            return major, minor

    # cuisine_type 沒訊號 → 退到店名 + 推薦菜（不分層，純最左）
    match_hint, _ = _prepare(f"{name}、{items}")
    hit = _first_hit(match_hint, _SHOP_TYPE + _NATION + _CATEGORY)
    if hit is None:
        return "", minor
    _, kw, major = hit
    return major, minor or kw
