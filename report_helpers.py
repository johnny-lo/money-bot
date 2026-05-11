"""報表用純函式：對比、Top N、異常偵測、迷你圖、儲蓄率、預算狀態。

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
