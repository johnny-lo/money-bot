"""報表用純函式：對比、Top N、異常偵測、迷你圖、儲蓄率、預算狀態、四桶水位。

所有函式都是純函式（沒有 DB / 網路 / 環境變數副作用），方便用 pytest 測試。
"""
from __future__ import annotations
from datetime import date, datetime, timedelta


# ─── 對比上週/上月 ────────────────────────────────────────────

def compare(curr: int, prev: int) -> str:
    """回傳格式化的對比字串。

    curr=12000, prev=10000 → "↑20% (上期 $10,000)"
    curr=8000,  prev=10000 → "↓20% (上期 $10,000)"
    curr=10000, prev=10000 → "持平 (上期 $10,000)"
    curr=12000, prev=0     → "首期 (無上期資料)"
    """
    if prev == 0:
        return "首期 (無上期資料)" if curr > 0 else "—"
    pct = (curr - prev) / prev * 100
    if abs(pct) < 0.5:
        return f"持平 (上期 ${prev:,})"
    arrow = "↑" if pct > 0 else "↓"
    return f"{arrow}{abs(pct):.0f}% (上期 ${prev:,})"


# ─── 單筆最大 Top N ───────────────────────────────────────────

def top_n_expenses(records: list[dict], n: int = 3) -> list[dict]:
    """從帳目清單抓金額最大的 N 筆。

    records: [{"item": str, "amount": int, "category": str, "date": "M/D"}]
    回傳同格式，按金額由大到小排序，最多 N 筆。
    """
    return sorted(records, key=lambda r: r["amount"], reverse=True)[:n]


def format_top_n(records: list[dict]) -> str:
    """把 top_n_expenses() 結果排成多行字串供 embed 用。"""
    if not records:
        return "（無）"
    lines = []
    for i, r in enumerate(records, 1):
        cat = f" `{r['category']}`" if r.get("category") else ""
        lines.append(f"{i}. **{r['item']}** ${r['amount']:,}{cat} · {r.get('date', '')}")
    return "\n".join(lines)


# ─── 異常偵測 ─────────────────────────────────────────────────

def detect_anomalies(
    current: dict[str, int],
    history: list[dict[str, int]],
    threshold_pct: float = 50.0,
) -> list[dict]:
    """跟歷史均值比，找出超出閾值的分類。

    current: {category: amount} 本期支出
    history: [{category: amount}, ...] 過去 N 期支出
    threshold_pct: 高於均值多少百分比算異常（預設 50%）

    回傳 [{"category": str, "current": int, "avg": int, "pct": float}, ...]，按 pct 由大到小
    """
    if not history:
        return []
    out: list[dict] = []
    for cat, curr_amount in current.items():
        if curr_amount <= 0:
            continue
        past = [h.get(cat, 0) for h in history]
        avg = sum(past) / len(past) if past else 0
        if avg <= 0:
            continue  # 從未有過這個分類就不算異常（新分類）
        pct = (curr_amount - avg) / avg * 100
        if pct >= threshold_pct:
            out.append({
                "category": cat,
                "current": curr_amount,
                "avg": int(avg),
                "pct": pct,
            })
    return sorted(out, key=lambda x: x["pct"], reverse=True)


def format_anomalies(anomalies: list[dict]) -> str:
    """把異常清單排成字串。"""
    if not anomalies:
        return ""
    lines = []
    for a in anomalies:
        lines.append(
            f"⚠️ **{a['category']}** ${a['current']:,}，比均值 ${a['avg']:,} 高 {a['pct']:.0f}%"
        )
    return "\n".join(lines)


# ─── 迷你長條 / 折線（unicode blocks）────────────────────────

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[int]) -> str:
    """用 unicode block 字元畫迷你折線（單行字串）。

    [1,3,2,5,4] → 一行 5 個 block 字元，最高的對到 █，最低的對到 ▁
    全 0 / 空陣列 → "（無資料）"
    """
    if not values:
        return "（無資料）"
    mx = max(values)
    mn = min(values)
    if mx == mn:
        return _BLOCKS[3] * len(values)  # 全部相同 → 中間高度
    span = mx - mn
    levels = len(_BLOCKS) - 1
    return "".join(
        _BLOCKS[min(levels, int((v - mn) / span * levels))]
        for v in values
    )


def daily_heatmap(daily_amounts: list[int]) -> str:
    """週一到週日的每日支出迷你長條圖。

    daily_amounts: 長度 7，週一(index 0) → 週日(index 6) 各日支出
    回傳多行：每行 = "週X ▆  $X,XXX"
    """
    if len(daily_amounts) != 7:
        return "（資料異常）"
    weekday_names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    bars = sparkline(daily_amounts)
    return "\n".join(
        f"`{n}` {b}  ${a:,}"
        for n, b, a in zip(weekday_names, bars, daily_amounts)
    )


# ─── 儲蓄率 ──────────────────────────────────────────────────

def savings_rate(income: int, expense: int) -> float | None:
    """儲蓄率 = (income - expense) / income * 100。

    income 為 0 時回傳 None（沒收入算不出比率）。
    可以是負值（支出 > 收入）。
    """
    if income <= 0:
        return None
    return (income - expense) / income * 100


def format_savings_rate(income: int, expense: int) -> str:
    """把儲蓄率排成顯示字串。"""
    rate = savings_rate(income, expense)
    if rate is None:
        return f"本月無收入，淨支出 ${expense - income:,}"
    surplus = income - expense
    sign = "+" if surplus >= 0 else "-"
    return f"{rate:+.0f}% (結餘 {sign}${abs(surplus):,})"


# ─── 預算狀態 ────────────────────────────────────────────────

def budget_status(
    expense: int, budget: int, day_of_month: int, days_in_month: int,
) -> str | None:
    """預算進度評估。

    budget 為 0/負 → 回 None（沒設預算）
    expense > budget → "⚠️ 超支 $XXX (XX%)"
    支出進度 / 月份進度 比較 → "🟢 進度健康" / "🟡 略快" / "🔴 太快"
    """
    if budget <= 0:
        return None
    used_pct = expense / budget * 100
    time_pct = day_of_month / days_in_month * 100
    if expense > budget:
        over = expense - budget
        return f"⚠️ 已超支 ${over:,} ({used_pct:.0f}% 預算)"
    remaining = budget - expense
    days_left = days_in_month - day_of_month
    diff = used_pct - time_pct
    if diff < -5:
        signal = "🟢 進度健康"
    elif diff < 10:
        signal = "🟡 進度略快"
    else:
        signal = "🔴 進度過快"
    return f"{signal}：已用 ${expense:,}/{budget:,} ({used_pct:.0f}%)，剩 ${remaining:,}，還 {days_left} 天"


# ─── 日期工具 ────────────────────────────────────────────────

def week_range(d: date) -> tuple[date, date]:
    """回傳 d 所在週的（週一, 週日）。"""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def previous_week_range(d: date) -> tuple[date, date]:
    """回傳 d 所在週的上一週（週一, 週日）。"""
    mon, _ = week_range(d)
    prev_mon = mon - timedelta(days=7)
    return prev_mon, prev_mon + timedelta(days=6)


def month_range(year: int, month: int) -> tuple[date, date]:
    """回傳指定月份的（1 號, 月底）。"""
    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def previous_month(year: int, month: int) -> tuple[int, int]:
    """回傳上一個 (year, month)。"""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def is_first_sunday(d: date) -> bool:
    """判斷 d 是不是當月第一個週日。"""
    return d.weekday() == 6 and d.day <= 7


# ─── 四桶水位（投資 / 固定 / 生活 / 爽）──────────────────────────────
#
# 這是跟大組**不同的軸**：大組回答「錢花在什麼」，桶回答「這筆錢該不該花」。
# 存在的理由：記帳助理若只看得到單筆金額，就只能用金額大小論斷，於是每筆稍大的
# 都被唸——但花三萬買 ETF 是好事，第五杯手搖才該被挑眉。有桶位才講得準。

BUCKET_INVEST, BUCKET_FIXED, BUCKET_LIVING, BUCKET_FUN = "投資", "固定", "生活", "爽"
BUCKET_ORDER = (BUCKET_INVEST, BUCKET_FIXED, BUCKET_LIVING, BUCKET_FUN)
BUCKET_ICONS = {BUCKET_INVEST: "🏦", BUCKET_FIXED: "🏠", BUCKET_LIVING: "🍚", BUCKET_FUN: "🎉"}

# 固定桶不參與「用量 vs 月份進度」的比較。理由：房租車貸是月初一次付清的，
# 1 號付完就 100%，拿它跟「月份進度 3%」比會得出「你花太快」的荒謬結論。
# 它也不該被唸——不可壓縮的支出唸了也沒用。
BUCKETS_SKIP_PACING = frozenset({BUCKET_FIXED})

# 細類 → 桶。細類清單見 categorize.CATEGORIES（單一真相在那邊，這裡只做映射）。
CATEGORY_BUCKETS: dict[str, str] = {
    "投資":     BUCKET_INVEST,
    "居住水電": BUCKET_FIXED,    # 房租/管理費/水電瓦斯：不可壓縮
    "分期保險": BUCKET_FIXED,    # 車貸/手機分期/保險：已經簽約的義務
    "交通":     BUCKET_LIVING,
    "三餐":     BUCKET_LIVING,
    "食材":     BUCKET_LIVING,
    "超商":     BUCKET_LIVING,
    "日用品":   BUCKET_LIVING,   # 紙巾清潔等消耗品;大額家電已拆到「家電3C」
    "醫療":     BUCKET_LIVING,
    "家電3C":   BUCKET_FUN,      # 電視/手機/耐久財：是想要不是需要
    "聚餐":     BUCKET_FUN,
    "飲料零食": BUCKET_FUN,
    "服飾":     BUCKET_FUN,
    "娛樂":     BUCKET_FUN,
    "其他":     BUCKET_LIVING,   # 保守：兜不到類的不灌進爽桶，免得被無辜唸
}


def parse_bucket_ratios(spec: str | None, n: int = 4) -> tuple[float, ...]:
    """解析 "投資:固定:生活:爽" 比例（例 "2:4:2:2"），正規化成加總為 1 的分數。

    數量不符/格式錯誤/含負數/全零一律回等分——設定寫壞不該讓功能整個消失。
    """
    default = tuple(1 / n for _ in range(n))
    if not spec:
        return default
    parts = [p.strip() for p in str(spec).replace("／", "/").replace("/", ":").split(":")]
    if len(parts) != n:
        return default
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return default
    if any(x < 0 for x in nums) or sum(nums) <= 0:
        return default
    total = sum(nums)
    return tuple(x / total for x in nums)


def bucket_totals(categories: list[dict]) -> tuple[dict[str, int], int]:
    """把 query_monthly_data() 的 categories 攤成各桶總額。

    回 (每桶金額, 未分類金額)。**未分類要單獨回**：記帳當下 category 是 NULL、
    要等週日 AI 分類才會落桶，不揭露的話桶位會被低估，助理就會過度樂觀。
    """
    totals = {b: 0 for b in BUCKET_ORDER}
    uncategorized = 0
    for row in categories or []:
        amount = int(row.get("amount") or 0)
        bucket = CATEGORY_BUCKETS.get(row.get("name") or "")
        if bucket is None:
            uncategorized += amount
        else:
            totals[bucket] += amount
    return totals, uncategorized


def format_bucket_context(
    income: int,
    categories: list[dict],
    ratios: tuple[float, float, float],
    *,
    day_of_month: int,
    days_in_month: int,
    basis: str = "本月收入",
) -> str | None:
    """組出給 AI 角色讀的四桶水位文字。income <= 0 回 None（沒基準就不要瞎猜）。

    回 None 時呼叫端應該完全不傳 context，讓角色走「沒有水位資訊」的保守模式。
    """
    if income <= 0:
        return None
    totals, uncategorized = bucket_totals(categories)
    lines = [f"本月{len(BUCKET_ORDER)}桶水位（基準：{basis} ${income:,}）"]
    for bucket, ratio in zip(BUCKET_ORDER, ratios):
        budget = int(round(income * ratio))
        spent = totals[bucket]
        pct = round(spent / budget * 100) if budget > 0 else 0
        note = "，月初就付清、不看進度也不用唸" if bucket in BUCKETS_SKIP_PACING else ""
        lines.append(
            f"{BUCKET_ICONS[bucket]} {bucket}：${spent:,} / ${budget:,}（{pct}%{note}）"
        )
    if uncategorized:
        lines.append(
            f"⏳ 尚未分類 ${uncategorized:,}（週日 AI 分類後才會落桶，"
            f"所以上面各桶是**低估**的，講話別太樂觀）"
        )
    time_pct = round(day_of_month / days_in_month * 100) if days_in_month else 0
    lines.append(f"月份進度：{day_of_month}/{days_in_month} 天（{time_pct}%）")
    return "\n".join(lines)
