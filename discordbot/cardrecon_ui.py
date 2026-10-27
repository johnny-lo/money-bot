"""刷卡比對的 Discord 端：週日清單卡（每頁 ≤25 筆）＋「全部補記」按鈕＋「忽略」下拉。

元件用 DynamicItem：custom_id 自帶 batch，bot 重啟後不需要記憶體狀態就能接手。只有本人能按。
"""
import os

import discord

from cardrecon import hints, repo
from cardrecon.types import Charge, WeeklyResult
from database import SessionLocal

from .bridge import post_sync

_SRC = {"sinopac_daily": "永豐", "ctbc_statement": "中信", "ctbc_line": "中信"}
_MARK = {"ignored": "已忽略", "matched": "✅ 已有帳", "recorded": "📝 已補記"}
COLOR = 0xE67E22


def _owner_id() -> int | None:
    v = os.getenv("AUTOFIX_OWNER_USER_ID", "").strip()
    return int(v) if v.isdigit() else None


def can_act(user_id: int, owner_id: int | None) -> str | None:
    if owner_id is None:
        return "還沒設定 AUTOFIX_OWNER_USER_ID，沒有人能操作"
    if user_id != owner_id:
        return "只有卡主本人能按"
    return None


_GROUP_LABEL = dict(hints.GROUPS)


def line(c: Charge, status: str = "unmatched", hint: str | None = None) -> str:
    when = f"{c.charge_date:%m/%d} {c.charge_time}" if c.charge_time else f"{c.charge_date:%m/%d}"
    s = f"{when} {_SRC.get(c.source, c.source)} {c.region or ''} ${c.amount:,}"   # 只寫銀行，不標末四碼
    if c.merchant:
        s = f"{s} {c.merchant}"
    elif c.merchant_type:                                 # 中信 LINE 的網路消費只有商店類型
        s = f"{s} （{c.merchant_type}）"
    s = " ".join(s.split())
    s = f"{s} · {hint}" if hint else s
    if status == "ignored":
        return f"~~{s}~~ {_MARK[status]}"
    return f"{s} {_MARK[status]}" if status in _MARK else s


def page_embed(batch: str, items: list[tuple[int, Charge, str, str | None]], page: str = "",
               group: str | None = None) -> discord.Embed:
    todo = [c for _, c, s, _ in items if s == "unmatched"]
    head = f"第 {page} 頁：" if page else ""
    name = _GROUP_LABEL.get(group, "疑似漏記") if group else "疑似漏記"
    body = "\n".join(line(c, s, h) for _, c, s, h in items)
    e = discord.Embed(title=f"💳 {name} {head}{len(todo)} 筆，共 ${sum(c.amount for c in todo):,}",
                      description=body[:4096], color=COLOR)
    e.set_footer(text=f"刷卡比對 · {batch} · 下拉勾要忽略的，再按「全部補記」")
    return e


class RecordButton(discord.ui.DynamicItem[discord.ui.Button], template=r"cardrecon:record:(?P<batch>[\w-]+)"):
    def __init__(self, batch: str):
        super().__init__(discord.ui.Button(label="📝 全部補記", style=discord.ButtonStyle.success,
                                           custom_id=f"cardrecon:record:{batch}"))
        self.batch = batch

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["batch"])

    async def callback(self, interaction: discord.Interaction):
        why = can_act(interaction.user.id, _owner_id())
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        db = SessionLocal()
        try:
            res = repo.record(db, self.batch)
            group, items = repo.batch_view(db, self.batch)
        finally:
            db.close()
        await interaction.response.edit_message(embed=page_embed(self.batch, items, group=group), view=None)
        note = f"已補記 {res.recorded} 筆，共 ${res.total:,}"
        if res.matched:
            note += f"（另有 {res.matched} 筆這週已有帳，改成已配對）"
        await interaction.followup.send(f"{note}（by {interaction.user.display_name}）")


class IgnoreSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"cardrecon:ignore:(?P<batch>[\w-]+)"):
    def __init__(self, batch: str, options: list[discord.SelectOption]):
        super().__init__(discord.ui.Select(placeholder="勾選要忽略的（不補記）", min_values=1,
                                           max_values=len(options), options=options,
                                           custom_id=f"cardrecon:ignore:{batch}"))
        self.batch = batch

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        opts = [discord.SelectOption(label=o.label, value=o.value) for o in getattr(item, "options", [])]
        return cls(match["batch"], opts or [discord.SelectOption(label="-", value="0")])

    async def callback(self, interaction: discord.Interaction):
        why = can_act(interaction.user.id, _owner_id())
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        ids = [int(v) for v in (interaction.data or {}).get("values", [])]
        db = SessionLocal()
        try:
            repo.ignore(db, self.batch, ids)
            group, items = repo.batch_view(db, self.batch)
        finally:
            db.close()
        await interaction.response.edit_message(embed=page_embed(self.batch, items, group=group),
                                                view=page_view(self.batch, items))


class IgnoreAllButton(discord.ui.DynamicItem[discord.ui.Button], template=r"cardrecon:ignoreall:(?P<batch>[\w-]+)"):
    def __init__(self, batch: str):
        super().__init__(discord.ui.Button(label="🙈 全部忽略", style=discord.ButtonStyle.secondary,
                                           custom_id=f"cardrecon:ignoreall:{batch}"))
        self.batch = batch

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["batch"])

    async def callback(self, interaction: discord.Interaction):
        why = can_act(interaction.user.id, _owner_id())
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        db = SessionLocal()
        try:
            _, items = repo.batch_view(db, self.batch)
            n = repo.ignore(db, self.batch, [i for i, _, s, _ in items if s == "unmatched"])
            group, items = repo.batch_view(db, self.batch)
        finally:
            db.close()
        await interaction.response.edit_message(embed=page_embed(self.batch, items, group=group), view=None)
        await interaction.followup.send(f"已忽略 {n} 筆（by {interaction.user.display_name}）")


def page_view(batch: str, items: list[tuple[int, Charge, str, str | None]]) -> discord.ui.View | None:
    todo = [(i, c, h) for i, c, s, h in items if s == "unmatched"]
    if not todo:
        return None
    v = discord.ui.View(timeout=None)
    opts = [discord.SelectOption(label=line(c, hint=h)[:100], value=str(i)) for i, c, h in todo]
    v.add_item(IgnoreSelect(batch, opts))
    v.add_item(RecordButton(batch))
    v.add_item(IgnoreAllButton(batch))
    return v


def _chan() -> int | None:
    v = os.getenv("DISCORD_INVOICE_CHANNEL_ID", "").strip()
    return int(v) if v.isdigit() else None


_LINE_STATE = {"ok": "正常", "kicked": "被登出，要重新掃碼", "error": "錯誤", "starting": "啟動中"}


def line_summary(result: WeeklyResult) -> str | None:
    """週日卡片上的 LINE 中信通知摘要；沒有 listener 狀態（還沒上線）就不顯示。"""
    if result.line_state is None:
        return None
    label = _LINE_STATE.get(result.line_state, result.line_state)
    return f"📡 LINE 中信通知：本週 {result.line_charges} 筆 · 合併帳單 {result.merged} 筆 · 狀態 {label}"


def notify_weekly(result: WeeklyResult) -> None:
    chan = _chan()
    if not chan:
        return
    total = {}
    for _, group, _ in result.pages:
        total[group] = total.get(group, 0) + 1
    seen = {}
    for batch, group, chunk in result.pages:
        seen[group] = seen.get(group, 0) + 1
        items = [(i, c, "unmatched", h) for i, c, h in chunk]
        post_sync(chan, [page_embed(batch, items, page=f"{seen[group]}/{total[group]}", group=group)],
                  make_view=lambda b=batch, it=items: page_view(b, it))
    summary = line_summary(result)
    if summary:                                           # 沒有清單頁也發：listener 被登出要讓人看得到
        post_sync(chan, [discord.Embed(description=summary, color=COLOR)])
    bad = result.failed_mails + result.unparsed_mails
    if bad:
        post_sync(chan, [discord.Embed(
            title="⚠️ 刷卡比對：有信件沒讀進來",
            description=f"解密失敗 {result.failed_mails} 封、沒附件或解析 0 筆 {result.unparsed_mails} 封"
                        "（可能是銀行改版或密碼變了）", color=COLOR)])


def notify_failure(err: str) -> None:
    chan = _chan()
    if chan:
        post_sync(chan, [discord.Embed(title="❌ 刷卡比對失敗", description=err[:4000], color=0xE74C3C)])
