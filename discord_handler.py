import asyncio
import os
from datetime import datetime, timedelta
import aiohttp
import discord
from discord import app_commands
from sqlalchemy import func

from core import (
    HELP_TEXT,
    handle_categorize, fetch_invoices_data,
    record_expense_data, record_income_data,
    query_monthly_data, query_recent_data,
    update_expense_data, update_income_data,
    delete_expense_data, delete_income_data,
    list_recurring_data, add_recurring_data, delete_recurring_data,
    handle_image_data,
)
from auth import generate_report_token
from database import SessionLocal
from models import Transaction, Income

NGROK_DOMAIN = "your-ngrok-domain.ngrok-free.dev"
BASE_URL = f"https://{NGROK_DOMAIN}"

COLOR_EXPENSE = 0xE74C3C   # 紅
COLOR_INCOME  = 0x2ECC71   # 綠
COLOR_INFO    = 0x3498DB   # 藍
COLOR_PERSONA = 0x9B59B6   # 紫（木須龍）
COLOR_WARN    = 0xF1C40F   # 黃


def fmt_money(n: int) -> str:
    return f"${n:,}"


def fmt_dt(dt) -> str:
    return dt.strftime("%m/%d %H:%M")


# ─── Embed 工具 ─────────────────────────────────────────────

def persona_embed(text: str):
    if not text:
        return None
    return discord.Embed(description=f"🐉 {text}", color=COLOR_PERSONA)


def error_embed(msg: str) -> discord.Embed:
    return discord.Embed(title="⚠️ 錯誤", description=msg, color=COLOR_WARN)


def expense_recorded_embed(d: dict) -> discord.Embed:
    e = discord.Embed(title="💸 支出已記錄", color=COLOR_EXPENSE)
    e.add_field(name="品項", value=d["item"], inline=True)
    e.add_field(name="金額", value=fmt_money(d["amount"]), inline=True)
    if d.get("category"):
        e.add_field(name="分類", value=d["category"], inline=True)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def income_recorded_embed(d: dict) -> discord.Embed:
    e = discord.Embed(title="💰 收入已記錄", color=COLOR_INCOME)
    e.add_field(name="品項", value=d["item"], inline=True)
    e.add_field(name="金額", value=fmt_money(d["amount"]), inline=True)
    if d.get("category"):
        e.add_field(name="分類", value=d["category"], inline=True)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def monthly_summary_embed(d: dict) -> discord.Embed:
    income, expense, net = d["income"], d["expense"], d["net"]
    color = COLOR_EXPENSE if net > 0 else COLOR_INCOME
    e = discord.Embed(title=f"📊 {d['year']}/{d['month']:02d} 結算", color=color)
    e.add_field(name="💰 收入", value=fmt_money(income), inline=True)
    e.add_field(name="💸 支出", value=fmt_money(expense), inline=True)
    e.add_field(name="📋 淨支出", value=fmt_money(net), inline=True)
    cats = d.get("categories") or []
    if cats and expense > 0:
        lines = []
        for c in cats[:6]:
            pct = c["amount"] / expense * 100
            lines.append(f"`{c['name'][:8]:<8}` {fmt_money(c['amount'])} ({pct:.0f}%)")
        e.add_field(name="📂 支出分類", value="\n".join(lines), inline=False)
    return e


def recent_records_embed(records: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🔍 最近紀錄", color=COLOR_INFO)
    if not records:
        e.description = "目前還沒有任何記帳紀錄。"
        return e
    lines = []
    for r in records:
        icon = "💸" if r["type"] == "expense" else "💰"
        cat = f" `{r['category']}`" if r.get("category") else ""
        lines.append(
            f"{icon} `#{r['id']}` **{r['item']}** {fmt_money(r['amount'])}{cat}\n"
            f"　　_{fmt_dt(r['created_at'])}_"
        )
    e.description = "\n".join(lines)[:4096]
    return e


def report_embed(url: str) -> discord.Embed:
    return discord.Embed(
        title="📊 互動式報表",
        description=f"[👉 點此開啟報表]({url})\n_30 分鐘內有效_",
        color=COLOR_INFO,
    )


def update_embed(kind: str, d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "修改失敗"))
    color = COLOR_EXPENSE if kind == "expense" else COLOR_INCOME
    label = "支出" if kind == "expense" else "收入"
    e = discord.Embed(title=f"✏️ {label}已更新", color=color)
    e.add_field(name="原本", value=f"{d['old']['item']} {fmt_money(d['old']['amount'])}", inline=False)
    e.add_field(name="更新", value=f"{d['new']['item']} {fmt_money(d['new']['amount'])}", inline=False)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def delete_record_embed(kind: str, d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "刪除失敗"))
    color = COLOR_EXPENSE if kind == "expense" else COLOR_INCOME
    label = "支出" if kind == "expense" else "收入"
    return discord.Embed(
        title=f"🗑️ {label}已刪除",
        description=f"`#{d['id']}` {d['item']} {fmt_money(d['amount'])}",
        color=color,
    )


def recurring_list_embed(records: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🔄 固定收支清單", color=COLOR_INFO)
    if not records:
        e.description = "目前沒有任何固定收支項目。"
        return e
    lines = []
    for r in records:
        icon = "💰" if r["type"] == "income" else "💸"
        lines.append(
            f"{icon} `#{r['id']}` **{r['item']}** {fmt_money(r['amount'])}"
            f" _每月 {r['day_of_month']} 號_"
        )
    e.description = "\n".join(lines)[:4096]
    return e


def recurring_added_embed(d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "建立失敗"))
    color = COLOR_INCOME if d["type"] == "income" else COLOR_EXPENSE
    label = "收入" if d["type"] == "income" else "支出"
    e = discord.Embed(title=f"🔄 固定{label}已建立", color=color)
    e.add_field(name="品項", value=d["item"], inline=True)
    e.add_field(name="金額", value=fmt_money(d["amount"]), inline=True)
    e.add_field(name="日期", value=f"每月 {d['day_of_month']} 號", inline=True)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def recurring_deleted_embed(d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "取消失敗"))
    label = "收入" if d["type"] == "income" else "支出"
    return discord.Embed(
        title=f"🗑️ 固定{label}已取消",
        description=f"`#{d['id']}` {d['item']} {fmt_money(d['amount'])}",
        color=COLOR_INFO,
    )


def image_recorded_embed(d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "辨識失敗"))
    e = discord.Embed(title="📸 影像辨識記帳", color=COLOR_EXPENSE)
    if d["expenses"]:
        lines = [f"`#{x['id']}` {x['item']} {fmt_money(x['amount'])}" for x in d["expenses"]]
        e.add_field(name=f"💸 項目（{len(d['expenses'])} 筆）",
                    value="\n".join(lines)[:1024], inline=False)
    if d["discounts"]:
        lines = [f"`#{x['id']}` {x['item']} -{fmt_money(x['amount'])}" for x in d["discounts"]]
        e.add_field(name=f"🏷️ 折扣（{len(d['discounts'])} 筆）",
                    value="\n".join(lines)[:1024], inline=False)
        e.add_field(name="小計", value=fmt_money(d["total_expense"]), inline=True)
        e.add_field(name="折扣", value=f"-{fmt_money(d['total_discount'])}", inline=True)
        e.add_field(name="實付", value=fmt_money(d["actual"]), inline=True)
    else:
        e.add_field(name="總計", value=fmt_money(d["total_expense"]), inline=False)
    return e


def help_embed() -> discord.Embed:
    e = discord.Embed(title="📖 指令說明", color=COLOR_INFO)
    e.description = (
        "**💸 記帳**\n"
        "`/記帳 品名 金額` — 記支出\n"
        "`/收入 品名 金額` — 記收入\n"
        "📸 直接傳圖片 — AI 辨識記帳\n\n"
        "**🔍 查詢**\n"
        "`/查詢` — 本月結算\n"
        "`/最近` — 最近紀錄\n"
        "`/報表` — 互動式報表\n\n"
        "**✏️ 修改 / 刪除**\n"
        "`/修改 編號 品名 金額`\n"
        "`/修改收入 編號 品名 金額`\n"
        "`/刪除 編號`、`/刪除收入 編號`\n\n"
        "**🔄 固定收支**\n"
        "`/固定支出 品名 金額 日期`\n"
        "`/固定收入 品名 金額 日期`\n"
        "`/固定清單`、`/取消固定 編號`\n\n"
        "**🛠️ 其他**\n"
        "`/分類` — 觸發 AI 分類\n"
        "`/抓發票 [天數]` — 同步電子發票\n"
        "`/說明` — 顯示這份說明"
    )
    return e


# ─── Bot ─────────────────────────────────────────────────────

class MoneyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f"🐉 Discord Bot 已上線：{self.user}")

    async def on_message(self, message: discord.Message):
        # 只處理圖片附件，文字交給 slash commands
        if message.author == self.user or not message.attachments:
            return
        for att in message.attachments:
            if not (att.content_type and att.content_type.startswith("image/")):
                continue
            async with message.channel.typing():
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(att.url) as resp:
                            image_bytes = await resp.read()
                    data = handle_image_data(image_bytes)
                    embeds = [image_recorded_embed(data)]
                    pe = persona_embed(data.get("persona", ""))
                    if pe:
                        embeds.append(pe)
                    await message.channel.send(embeds=embeds)
                except Exception as e:
                    await message.channel.send(embed=error_embed(f"視覺大腦失敗：{e}"))
            return

    def _register_commands(self):
        tree = self.tree

        @tree.command(name="記帳", description="記錄一筆支出")
        @app_commands.describe(品名="支出項目", 金額="花費金額")
        async def cmd_expense(ix: discord.Interaction, 品名: str, 金額: int):
            await ix.response.defer()
            data = record_expense_data(品名, 金額)
            if not data["success"]:
                await ix.followup.send(embed=error_embed(data["error"]))
                return
            embeds = [expense_recorded_embed(data)]
            pe = persona_embed(data.get("persona", ""))
            if pe:
                embeds.append(pe)
            await ix.followup.send(embeds=embeds)

        @tree.command(name="收入", description="記錄一筆收入")
        @app_commands.describe(品名="收入項目", 金額="收入金額")
        async def cmd_income(ix: discord.Interaction, 品名: str, 金額: int):
            await ix.response.defer()
            data = record_income_data(品名, 金額)
            if not data["success"]:
                await ix.followup.send(embed=error_embed(data["error"]))
                return
            embeds = [income_recorded_embed(data)]
            pe = persona_embed(data.get("persona", ""))
            if pe:
                embeds.append(pe)
            await ix.followup.send(embeds=embeds)

        @tree.command(name="查詢", description="本月收支結算")
        async def cmd_query(ix: discord.Interaction):
            data = query_monthly_data()
            await ix.response.send_message(embed=monthly_summary_embed(data))

        @tree.command(name="最近", description="最近的記帳紀錄")
        @app_commands.describe(筆數="顯示筆數（1-10，預設 5）")
        async def cmd_recent(ix: discord.Interaction, 筆數: int = 5):
            limit = max(1, min(10, 筆數))
            records = query_recent_data(limit)
            await ix.response.send_message(embed=recent_records_embed(records))

        @tree.command(name="報表", description="產生互動式網頁報表")
        async def cmd_report(ix: discord.Interaction):
            token = generate_report_token(str(ix.user.id))
            url = f"{BASE_URL}/report?token={token}"
            await ix.response.send_message(embed=report_embed(url))

        @tree.command(name="修改", description="修改一筆支出")
        @app_commands.describe(編號="支出 ID", 品名="新品名", 金額="新金額")
        async def cmd_update_expense(ix: discord.Interaction, 編號: int, 品名: str, 金額: int):
            data = update_expense_data(編號, 品名, 金額)
            await ix.response.send_message(embed=update_embed("expense", data))

        @tree.command(name="修改收入", description="修改一筆收入")
        @app_commands.describe(編號="收入 ID", 品名="新品名", 金額="新金額")
        async def cmd_update_income(ix: discord.Interaction, 編號: int, 品名: str, 金額: int):
            data = update_income_data(編號, 品名, 金額)
            await ix.response.send_message(embed=update_embed("income", data))

        @tree.command(name="刪除", description="刪除一筆支出")
        @app_commands.describe(編號="支出 ID")
        async def cmd_delete_expense(ix: discord.Interaction, 編號: int):
            data = delete_expense_data(編號)
            await ix.response.send_message(embed=delete_record_embed("expense", data))

        @tree.command(name="刪除收入", description="刪除一筆收入")
        @app_commands.describe(編號="收入 ID")
        async def cmd_delete_income(ix: discord.Interaction, 編號: int):
            data = delete_income_data(編號)
            await ix.response.send_message(embed=delete_record_embed("income", data))

        @tree.command(name="固定支出", description="新增每月固定支出")
        @app_commands.describe(品名="項目", 金額="金額", 日期="每月幾號（1-28）")
        async def cmd_recurring_expense(ix: discord.Interaction, 品名: str, 金額: int, 日期: int):
            data = add_recurring_data("支出", 品名, 金額, 日期)
            await ix.response.send_message(embed=recurring_added_embed(data))

        @tree.command(name="固定收入", description="新增每月固定收入")
        @app_commands.describe(品名="項目", 金額="金額", 日期="每月幾號（1-28）")
        async def cmd_recurring_income(ix: discord.Interaction, 品名: str, 金額: int, 日期: int):
            data = add_recurring_data("收入", 品名, 金額, 日期)
            await ix.response.send_message(embed=recurring_added_embed(data))

        @tree.command(name="固定清單", description="查看所有固定收支")
        async def cmd_recurring_list(ix: discord.Interaction):
            records = list_recurring_data()
            await ix.response.send_message(embed=recurring_list_embed(records))

        @tree.command(name="取消固定", description="取消一個固定收支")
        @app_commands.describe(編號="固定收支 ID")
        async def cmd_recurring_delete(ix: discord.Interaction, 編號: int):
            data = delete_recurring_data(編號)
            await ix.response.send_message(embed=recurring_deleted_embed(data))

        @tree.command(name="分類", description="手動觸發 AI 自動分類")
        async def cmd_categorize(ix: discord.Interaction):
            await ix.response.defer()
            try:
                msg = handle_categorize()
                e = discord.Embed(title="🏷️ AI 分類完成", description=msg[:4000], color=COLOR_INFO)
            except Exception as ex:
                e = error_embed(str(ex))
            await ix.followup.send(embed=e)

        @tree.command(name="抓發票", description="同步電子發票（手機條碼載具）")
        @app_commands.describe(天數="抓近 N 天的發票（預設 1，今天）")
        async def cmd_fetch_invoice(ix: discord.Interaction, 天數: int = 1):
            await ix.response.defer()
            try:
                result = fetch_invoices_data(max(1, min(31, 天數)))
                e = discord.Embed(
                    title="🧾 發票同步結果",
                    description=f"```\n{result['summary'][:3900]}\n```",
                    color=COLOR_INFO,
                )
                embeds = [e]
                items_embed = _build_items_embed(result.get("new_items", []))
                if items_embed:
                    embeds.append(items_embed)
            except Exception as ex:
                embeds = [error_embed(str(ex))]
            await ix.followup.send(embeds=embeds)

        @tree.command(name="說明", description="顯示所有指令")
        async def cmd_help(ix: discord.Interaction):
            await ix.response.send_message(embed=help_embed())

        @tree.command(name="測試週報", description="立即觸發本週週報推到 #📊-報表查詢")
        async def cmd_test_weekly(ix: discord.Interaction):
            await ix.response.defer(ephemeral=True)
            try:
                notify_weekly_summary()
                await ix.followup.send("✅ 已觸發本週週報，請看 #📊-報表查詢", ephemeral=True)
            except Exception as ex:
                await ix.followup.send(f"⚠️ 失敗：{ex}", ephemeral=True)

        @tree.command(name="測試月報", description="立即觸發上月月報推到 #📊-報表查詢")
        async def cmd_test_monthly(ix: discord.Interaction):
            await ix.response.defer(ephemeral=True)
            try:
                notify_monthly_summary()
                await ix.followup.send("✅ 已觸發上月月報，請看 #📊-報表查詢", ephemeral=True)
            except Exception as ex:
                await ix.followup.send(f"⚠️ 失敗：{ex}", ephemeral=True)


def create_discord_bot() -> MoneyBot:
    bot = MoneyBot()
    set_bot(bot)
    return bot


# ─── Sync→Async bridge：給排程從另一個 thread 推訊息到 Discord 用 ──

_bot_instance: MoneyBot | None = None


def set_bot(bot: MoneyBot) -> None:
    global _bot_instance
    _bot_instance = bot


def _post_embeds_sync(channel_id: int, embeds: list[discord.Embed]) -> None:
    """Threadsafe：從非 async thread 投遞 embeds 到指定 channel。"""
    bot = _bot_instance
    if not bot or not channel_id:
        return
    loop = bot.loop
    if not loop or loop.is_closed():
        print("⚠️ Discord bot 還沒 ready，跳過通知")
        return

    async def _send():
        try:
            ch = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            await ch.send(embeds=embeds)
        except Exception as e:
            print(f"⚠️ Discord 通知失敗 (channel {channel_id})：{e}")

    asyncio.run_coroutine_threadsafe(_send(), loop)


def _build_items_embed(new_items: list[dict]) -> discord.Embed | None:
    """把新增的發票品項排版成 embed（超過 4000 字裁切）。沒有就回 None。"""
    if not new_items:
        return None
    lines = []
    used = 0
    for it in new_items:
        line = f"• {it['date']}　{it['item']}　${it['price']:,}"
        if used + len(line) + 1 > 3900:
            lines.append(f"…還有 {len(new_items) - len(lines)} 筆")
            break
        lines.append(line)
        used += len(line) + 1
    total = sum(it["price"] for it in new_items)
    e = discord.Embed(
        title=f"🆕 新增明細（{len(new_items)} 筆，合計 ${total:,}）",
        description="\n".join(lines),
        color=COLOR_INFO,
    )
    return e


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
    items_embed = _build_items_embed(new_items or [])
    if items_embed:
        embeds.append(items_embed)
    _post_embeds_sync(int(chan_id), embeds)


# ─── 週報 / 月報 DB 查詢 ───────────────────────────────────────

def _query_period(start: "date", end: "date") -> dict:
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
) -> str:
    """用較強的 Gemini 模型生成期間評語（木須龍口吻）。失敗回空字串。"""
    try:
        from gemini import gemini_text, PERSONA_TEXT
    except Exception:
        return ""
    group_str = "、".join(f"{g['name']} {g['amount']}元" for g in groups) or "（無）"
    top_cats = "、".join(f"{c['name']} {c['amount']}元" for c in categories[:5]) or "（無）"
    prompt = (
        f"{PERSONA_TEXT}\n\n---\n"
        f"以下是主人{period_kind}（{period_label}）的記帳結算：\n"
        f"- 收入：{income} 元\n"
        f"- 支出：{expense} 元\n"
        f"- 淨支出：{net} 元\n"
        f"- 大組支出分布：{group_str}\n"
        f"- 前 5 大細類：{top_cats}\n\n"
        f"請用你的角色口吻給一段 2–3 句的{period_kind}理財評語，"
        f"必須點出最大支出來源、給一個具體可執行的建議。"
        f"不要列點、不要加標題、直接給評語文字。"
    )
    model = os.getenv("WEEKLY_MODEL", "gemini-pro-latest")
    try:
        return gemini_text(prompt, model=model).strip()
    except Exception as e:
        msg = str(e)
        print(f"⚠️ {period_kind}評語生成失敗（{model}）：{msg}")
        return f"⚠️ AI 評語生成失敗：{msg}"


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

    comment = _generate_ai_comment(total_i, total_e, net, groups, categories, week_label, "本週")
    if comment:
        e.add_field(name="🐉 本週評語", value=comment[:1024], inline=False)

    e.set_footer(text="🐉 每週日 21:00 自動結算")
    _post_embeds_sync(int(chan_id), [e])


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

    comment = _generate_ai_comment(total_i, total_e, net, groups, categories, f"{y}/{m:02d}", "本月")
    if comment:
        e.add_field(name="🐉 本月評語", value=comment[:1024], inline=False)

    e.set_footer(text="🐉 每月第一個週日 21:00 自動結算")
    _post_embeds_sync(int(chan_id), [e])
