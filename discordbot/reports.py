"""週報 / 月報 / 發票通知：DB 彙總查詢 + embed 組裝 + 經 bridge 推到 Discord 頻道。"""
import os
from datetime import datetime, timedelta

import discord
from sqlalchemy import func

from database import SessionLocal
from models import Transaction, Income
from .bridge import post_embeds_sync
from .embeds import (
    COLOR_EXPENSE, COLOR_INCOME, COLOR_WARN,
    fmt_money, build_items_embed, invoice_sync_failed_embed,
)


def _query_period(start, end) -> dict:
    """查詢一段期間（含起訖兩日）的支出/收入/分類/Top N/每日金額。"""
    db = SessionLocal()
    try:
        total_e = db.query(func.sum(Transaction.price)).filter(
            func.date(Transaction.created_at) >= start,
            func.date(Transaction.created_at) <= end,
        ).scalar() or 0
        total_i = db.query(func.sum(Income.amount)).filter(
            func.date(Income.created_at) >= start,
            func.date(Income.created_at) <= end,
        ).scalar() or 0
        cat_rows = db.query(
            Transaction.category, func.sum(Transaction.price),
        ).filter(
            func.date(Transaction.created_at) >= start,
            func.date(Transaction.created_at) <= end,
        ).group_by(Transaction.category).all()
        categories = sorted(
            [{"name": (c or "未分類"), "amount": int(a or 0)} for c, a in cat_rows],
            key=lambda x: x["amount"], reverse=True,
        )
        # Top N 單筆
        top_rows = db.query(Transaction).filter(
            func.date(Transaction.created_at) >= start,
            func.date(Transaction.created_at) <= end,
        ).order_by(Transaction.price.desc()).limit(5).all()
        top_records = [{
            "item": t.item,
            "amount": int(t.price),
            "category": t.category or "未分類",
            "date": t.created_at.strftime("%m/%d") if t.created_at else "",
        } for t in top_rows]
        # 每日金額（給週報用：start 開始連續 7 天）
        day_rows = db.query(
            func.date(Transaction.created_at).label("d"),
            func.sum(Transaction.price).label("s"),
        ).filter(
            func.date(Transaction.created_at) >= start,
            func.date(Transaction.created_at) <= end,
        ).group_by("d").all()
        day_map = {r.d: int(r.s or 0) for r in day_rows}
    finally:
        db.close()
    return {
        "total_e": int(total_e),
        "total_i": int(total_i),
        "categories": categories,
        "top_records": top_records,
        "day_map": day_map,
    }


def _aggregate_groups(categories: list[dict]) -> list[dict]:
    """細類 → 大組聚合。輸入排序好的 categories，回傳依 GROUP_ORDER 排序的 groups。"""
    from categorize import category_group, GROUP_ORDER
    group_amounts: dict[str, int] = {}
    for c in categories:
        g = category_group(c["name"] if c["name"] != "未分類" else None)
        group_amounts[g] = group_amounts.get(g, 0) + c["amount"]
    return sorted(
        [{"name": g, "amount": a} for g, a in group_amounts.items() if a > 0],
        key=lambda x: GROUP_ORDER.index(x["name"]) if x["name"] in GROUP_ORDER else 99,
    )


def _generate_ai_comment(
    income: int, expense: int, net: int,
    groups: list[dict], categories: list[dict],
    period_label: str, period_kind: str,
    *,
    vs_prev: str = "",
    savings: str = "",
    anomalies: list[dict] | None = None,
    top_records: list[dict] | None = None,
) -> str:
    """用 codex CLI（ChatGPT 訂閱，gpt-5.5）生成期間評語（錢鼠阿財口吻）。失敗回錯誤訊息字串。

    傳入報表已算好的 vs 上期對比 / 儲蓄率 / 異常暴增 / 單筆 Top 3，
    讓評語能講出具體數字與可執行建議，而非空泛鼓勵。
    """
    try:
        from codex_cli import codex_text
        from gemini import PERSONA_TEXT
    except Exception:
        return ""

    group_str = "、".join(f"{g['name']} {g['amount']}元" for g in groups) or "（無）"
    top_cats = "、".join(f"{c['name']} {c['amount']}元" for c in categories[:5]) or "（無）"
    top3 = "、".join(
        f"{r['item']} {r['amount']}元" for r in (top_records or [])[:3]
    ) or "（無）"
    anomaly_str = "、".join(
        f"{a['category']}（{a['current']}元，較近期均值 +{a['pct']:.0f}%）"
        for a in (anomalies or [])[:3]
    ) or "（無明顯異常）"

    facts = [
        f"- 收入：{income} 元",
        f"- 支出：{expense} 元（vs 上期：{vs_prev or '—'}）",
        f"- 淨支出：{net} 元",
    ]
    if savings:
        facts.append(f"- 儲蓄率：{savings}")
    facts += [
        f"- 大組支出分布：{group_str}",
        f"- 前 5 大細類：{top_cats}",
        f"- 單筆最大三筆：{top3}",
        f"- 異常暴增分類：{anomaly_str}",
    ]

    if period_kind == "本月":
        ask = (
            "請用你的角色口吻給一段 3–4 句的月度理財評語：先點出本月相對上月的整體變化"
            "（用儲蓄率或支出增減來講），再指出最大支出來源與任何異常暴增的分類，"
            "最後給「下個月」一個具體、可執行的行動建議——要明確到哪一類、怎麼做、目標省多少。"
        )
    else:
        ask = (
            "請用你的角色口吻給一段 2–3 句的本週理財評語：點出本週最大支出來源、"
            "與上週相比的變化，並給一個「這週就能做」的具體小調整建議。"
        )

    prompt = (
        f"{PERSONA_TEXT}\n\n---\n"
        f"以下是主人{period_kind}（{period_label}）的記帳結算：\n"
        + "\n".join(facts)
        + "\n\n" + ask
        + "請直接給一段口語評語文字，不要列點、不要加標題、不要重複貼上面的數字清單。"
    )
    try:
        return codex_text(prompt).strip()
    except Exception as e:
        msg = str(e)
        print(f"⚠️ {period_kind}評語生成失敗（codex）：{msg}")
        return f"⚠️ AI 評語生成失敗：{msg}"


def notify_invoice_sync(summary: str, new_items: list[dict] | None = None) -> None:
    """每日 21:00 抓發票完，自動通知到 #🧾-發票通知。"""
    chan_id = os.getenv("DISCORD_INVOICE_CHANNEL_ID")
    if not chan_id:
        return
    e = discord.Embed(
        title="🧾 發票同步完成",
        description=f"```\n{summary[:3900]}\n```",
        color=COLOR_WARN,
        timestamp=datetime.now(),
    )
    e.set_footer(text="🐉 每日 21:00 自動同步")
    embeds = [e]
    items_embed = build_items_embed(new_items or [])
    if items_embed:
        embeds.append(items_embed)
    post_embeds_sync(int(chan_id), embeds)


def notify_invoice_failure(result: dict) -> None:
    """發票同步失敗 → 發失敗卡到 #🧾-發票通知。"""
    chan_id = os.getenv("DISCORD_INVOICE_CHANNEL_ID")
    if not chan_id:
        return
    post_embeds_sync(int(chan_id), [invoice_sync_failed_embed(result)])


def notify_weekly_summary() -> None:
    """週日 21:00 自動 post 本週（週一到週日）結算到 #📊-報表查詢。"""
    from report_helpers import (
        week_range, previous_week_range,
        compare, format_top_n, detect_anomalies, format_anomalies, daily_heatmap,
    )

    chan_id = os.getenv("DISCORD_REPORT_CHANNEL_ID")
    if not chan_id:
        return

    today = datetime.now().date()
    monday, sunday = week_range(today)
    prev_mon, prev_sun = previous_week_range(today)

    curr = _query_period(monday, sunday)
    prev = _query_period(prev_mon, prev_sun)

    total_e, total_i = curr["total_e"], curr["total_i"]
    net = total_e - total_i
    categories = curr["categories"]
    groups = _aggregate_groups(categories)

    # 每日支出（週一→週日）
    daily_amounts = [
        curr["day_map"].get(monday + timedelta(days=i), 0)
        for i in range(7)
    ]

    # 近 4 週分類歷史（不含本週）
    history: list[dict[str, int]] = []
    for w in range(1, 5):
        s = monday - timedelta(days=7 * w)
        e_ = s + timedelta(days=6)
        h = _query_period(s, e_)
        history.append({c["name"]: c["amount"] for c in h["categories"]})

    color = COLOR_EXPENSE if net > 0 else COLOR_INCOME
    week_label = f"{monday.month}/{monday.day}–{sunday.month}/{sunday.day}"
    e = discord.Embed(title=f"📊 本週結算 ({week_label})", color=color)
    e.add_field(name="💰 收入", value=fmt_money(total_i), inline=True)
    e.add_field(name="💸 支出", value=fmt_money(total_e), inline=True)
    e.add_field(name="📋 淨支出", value=fmt_money(net), inline=True)

    # A. 跟上週對比
    e.add_field(
        name="📈 vs 上週",
        value=f"支出 {compare(total_e, prev['total_e'])}",
        inline=False,
    )

    if groups and total_e > 0:
        lines = [
            f"`{g['name']:<4}` {fmt_money(g['amount'])} ({g['amount'] / total_e * 100:.0f}%)"
            for g in groups
        ]
        e.add_field(name="🗂️ 大組分布", value="\n".join(lines), inline=False)

    if categories and total_e > 0:
        lines = [
            f"`{c['name'][:8]:<8}` {fmt_money(c['amount'])} ({c['amount'] / total_e * 100:.0f}%)"
            for c in categories[:8]
        ]
        e.add_field(name="📂 細類分布", value="\n".join(lines), inline=False)

    # B. 單筆最大 Top 3
    if curr["top_records"]:
        e.add_field(name="🔝 最大三筆", value=format_top_n(curr["top_records"][:3]), inline=False)

    # F. 每日支出迷你長條
    if total_e > 0:
        e.add_field(name="📅 每日支出", value=daily_heatmap(daily_amounts), inline=False)

    # D. 異常偵測
    current_by_cat = {c["name"]: c["amount"] for c in categories}
    anomalies = detect_anomalies(current_by_cat, history)
    if anomalies:
        e.add_field(name="🚨 異常分類", value=format_anomalies(anomalies[:3]), inline=False)

    comment = _generate_ai_comment(
        total_i, total_e, net, groups, categories, week_label, "本週",
        vs_prev=compare(total_e, prev["total_e"]),
        anomalies=anomalies,
        top_records=curr["top_records"],
    )
    if comment:
        e.add_field(name="🐉 本週評語", value=comment[:1024], inline=False)

    e.set_footer(text="🐉 每週日 21:00 自動結算")
    post_embeds_sync(int(chan_id), [e])


def notify_monthly_summary() -> None:
    """post 上月結算到 #📊-報表查詢。由每月第一個週日的 weekly_pipeline 串接呼叫。"""
    from report_helpers import (
        month_range, previous_month,
        compare, format_top_n, detect_anomalies, format_anomalies,
        sparkline, format_savings_rate, budget_status,
    )
    from calendar import monthrange

    chan_id = os.getenv("DISCORD_REPORT_CHANNEL_ID")
    if not chan_id:
        return

    now = datetime.now()
    y, m = previous_month(now.year, now.month)
    py, pm = previous_month(y, m)  # 上上月（給對比）
    start, end = month_range(y, m)
    prev_start, prev_end = month_range(py, pm)

    curr = _query_period(start, end)
    prev = _query_period(prev_start, prev_end)

    total_e, total_i = curr["total_e"], curr["total_i"]
    net = total_e - total_i
    categories = curr["categories"]
    groups = _aggregate_groups(categories)

    # G. 近 6 個月支出 sparkline
    six_month_totals: list[int] = []
    six_month_labels: list[str] = []
    cy, cm = y, m
    for _ in range(6):
        s, e_ = month_range(cy, cm)
        six_month_totals.append(_query_period(s, e_)["total_e"])
        six_month_labels.append(f"{cm}月")
        cy, cm = previous_month(cy, cm)
    six_month_totals.reverse()
    six_month_labels.reverse()

    # D. 近 4 個月分類歷史（不含本月）
    history: list[dict[str, int]] = []
    cy, cm = py, pm  # 從上上月開始往前
    for _ in range(4):
        s, e_ = month_range(cy, cm)
        h = _query_period(s, e_)
        history.append({c["name"]: c["amount"] for c in h["categories"]})
        cy, cm = previous_month(cy, cm)

    color = COLOR_EXPENSE if net > 0 else COLOR_INCOME
    e = discord.Embed(title=f"📊 {y}/{m:02d} 上月結算", color=color)
    e.add_field(name="💰 收入", value=fmt_money(total_i), inline=True)
    e.add_field(name="💸 支出", value=fmt_money(total_e), inline=True)
    e.add_field(name="📋 淨支出", value=fmt_money(net), inline=True)

    # A. 跟上上月對比
    e.add_field(
        name="📈 vs 上月",
        value=f"支出 {compare(total_e, prev['total_e'])}",
        inline=False,
    )

    # E. 儲蓄率
    e.add_field(name="💰 儲蓄率", value=format_savings_rate(total_i, total_e), inline=False)

    # C. 預算狀態
    try:
        budget = int(os.getenv("MONTHLY_BUDGET", "0") or "0")
    except ValueError:
        budget = 0
    if budget > 0:
        days_in_month = monthrange(y, m)[1]
        bstat = budget_status(total_e, budget, days_in_month, days_in_month)
        if bstat:
            e.add_field(name="💼 預算", value=bstat, inline=False)

    if groups and total_e > 0:
        lines = [
            f"`{g['name']:<4}` {fmt_money(g['amount'])} ({g['amount'] / total_e * 100:.0f}%)"
            for g in groups
        ]
        e.add_field(name="🗂️ 大組分布", value="\n".join(lines), inline=False)

    if categories and total_e > 0:
        lines = [
            f"`{c['name'][:8]:<8}` {fmt_money(c['amount'])} ({c['amount'] / total_e * 100:.0f}%)"
            for c in categories[:8]
        ]
        e.add_field(name="📂 細類分布", value="\n".join(lines), inline=False)

    # B. Top 3 單筆
    if curr["top_records"]:
        e.add_field(name="🔝 最大三筆", value=format_top_n(curr["top_records"][:3]), inline=False)

    # G. 6 個月 sparkline
    spark = sparkline(six_month_totals)
    e.add_field(
        name="📈 近 6 月支出走勢",
        value=f"`{spark}`\n{six_month_labels[0]} → {six_month_labels[-1]}（最高 ${max(six_month_totals):,} / 最低 ${min(six_month_totals):,}）",
        inline=False,
    )

    # D. 異常偵測
    current_by_cat = {c["name"]: c["amount"] for c in categories}
    anomalies = detect_anomalies(current_by_cat, history)
    if anomalies:
        e.add_field(name="🚨 異常分類", value=format_anomalies(anomalies[:3]), inline=False)

    comment = _generate_ai_comment(
        total_i, total_e, net, groups, categories, f"{y}/{m:02d}", "本月",
        vs_prev=compare(total_e, prev["total_e"]),
        savings=format_savings_rate(total_i, total_e),
        anomalies=anomalies,
        top_records=curr["top_records"],
    )
    if comment:
        e.add_field(name="🐉 本月評語", value=comment[:1024], inline=False)

    e.set_footer(text="🐉 每月第一個週日 21:00 自動結算")
    post_embeds_sync(int(chan_id), [e])
