"""刷卡比對的 Discord 端：週日清單卡（每頁 ≤25 筆）＋「全部補記」按鈕＋「忽略」下拉。

元件用 DynamicItem：custom_id 自帶 batch，bot 重啟後不需要記憶體狀態就能接手。只有本人能按。
"""
import os

import discord

from cardrecon import repo
from cardrecon.types import Charge, WeeklyResult
from database import SessionLocal

from .bridge import post_sync

_SRC = {"sinopac_daily": "永豐", "ctbc_statement": "中信"}
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


def line(c: Charge, status: str = "unmatched") -> str:
    s = f"{c.charge_date:%m/%d} {_SRC.get(c.source, c.source)}{c.card_last4} {c.region or ''} ${c.amount:,}"
    s = f"{s} {c.merchant}" if c.merchant else s
    s = " ".join(s.split())
    if status == "ignored":
        return f"~~{s}~~ {_MARK[status]}"
    return f"{s} {_MARK[status]}" if status in _MARK else s


def page_embed(batch: str, items: list[tuple[int, Charge, str]], page: str = "") -> discord.Embed:
    todo = [c for _, c, s in items if s == "unmatched"]
    head = f"第 {page} 頁：" if page else ""
    e = discord.Embed(title=f"💳 疑似漏記 {head}{len(todo)} 筆，共 ${sum(c.amount for c in todo):,}",
                      description="\n".join(line(c, s) for _, c, s in items), color=COLOR)
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
            items = repo.batch_items(db, self.batch)
        finally:
            db.close()
        await interaction.response.edit_message(embed=page_embed(self.batch, items), view=None)
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
            items = repo.batch_items(db, self.batch)
        finally:
            db.close()
        await interaction.response.edit_message(embed=page_embed(self.batch, items),
                                                view=page_view(self.batch, items))


def page_view(batch: str, items: list[tuple[int, Charge, str]]) -> discord.ui.View | None:
    todo = [(i, c) for i, c, s in items if s == "unmatched"]
    if not todo:
        return None
    v = discord.ui.View(timeout=None)
    opts = [discord.SelectOption(label=line(c)[:100], value=str(i)) for i, c in todo]
    v.add_item(IgnoreSelect(batch, opts))
    v.add_item(RecordButton(batch))
    return v


def _chan() -> int | None:
    v = os.getenv("DISCORD_INVOICE_CHANNEL_ID", "").strip()
    return int(v) if v.isdigit() else None


def notify_weekly(result: WeeklyResult) -> None:
    chan = _chan()
    if not chan:
        return
    n = len(result.pages)
    for k, (batch, chunk) in enumerate(result.pages, 1):
        items = [(i, c, "unmatched") for i, c in chunk]
        post_sync(chan, [page_embed(batch, items, page=f"{k}/{n}")],
                  make_view=lambda b=batch, it=items: page_view(b, it))
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
