"""信件規則引擎的 Discord 端：建議確認卡、每日報告、職缺／推銷摘要、歷史整理計畫卡。

元件用 DynamicItem：custom_id 自帶卡號／規則 id，bot 重啟後不需要記憶體狀態就能接手。只有本人能按。
"""
import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from database import SessionLocal
from mailrules import config, repo
from mailrules.types import MailHeader, Rule, RunReport

from .bridge import post_sync

COLOR = 0x3498DB
_FAIL_COLOR = 0xE74C3C
_MORE_RESERVE = 30            # daily_embed 截斷時留給「…還有 N 封」的字數


def _owner_id() -> int | None:
    v = os.getenv("AUTOFIX_OWNER_USER_ID", "").strip()
    return int(v) if v.isdigit() else None


def can_act(user_id: int, owner_id: int | None) -> str | None:
    if owner_id is None:
        return "還沒設定 AUTOFIX_OWNER_USER_ID，沒有人能操作"
    if user_id != owner_id:
        return "只有卡主本人能按"
    return None


def _today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def _cat(c: str) -> str:
    return config.LABELS.get(c, c)


def suggest_embed(card: str, rules: list[Rule], counts: dict) -> discord.Embed:
    cats = {r.category for r in rules}
    if len(cats) == 1:
        title = f"🤖 建議歸為『{_cat(next(iter(cats)))}』：{len(rules)} 個樣式"
    else:
        title = f"🤖 新寄件者分類建議：{len(rules)} 個樣式"
    lines = []
    for r in rules:
        n = counts.get((r.sender, r.subject_pattern))
        s = f"`{r.sender}`｜{r.subject_pattern}｜" + (f"{n} 封｜" if n is not None else "") + f"→ {_cat(r.category)}"
        lines.append(f"~~{s}~~ 已拒絕" if r.status == "rejected" else s)
    e = discord.Embed(title=title, description="\n".join(lines)[:4096], color=COLOR)
    e.set_footer(text=f"信件整理 · {card} · 下拉勾不要的，再按「確認」")
    return e


def digest_embed(title: str, headers: list[MailHeader]) -> discord.Embed:
    lines = []
    for h in headers:
        d = f"{h.sent_date:%m/%d}" if h.sent_date else "--/--"
        lines.append(f"{h.from_addr}｜{h.subject}｜{d}")
    return discord.Embed(title=title, description="\n".join(lines)[:4096], color=COLOR)


def daily_embed(rep: RunReport) -> discord.Embed:
    lines = []
    if not rep.applied:
        lines.append("⏸ 歷史整理完成前只分類、不動信件。")
    for (cat, kind), n in sorted(rep.counts.items()):
        lines.append(f"{_cat(cat)}｜{kind}｜{n} 封")
    lines.append(f"❓ 未知樣式：{rep.unknown_patterns} 個")
    if rep.failed:
        lines.append(f"⚠️ 失敗：{rep.failed} 封")
    if rep.protected:
        lines.append(f"🛡 安全網留在收件匣（看起來重要，我沒動）：{len(rep.protected)} 封")
        room = 4096 - len("\n".join(lines)) - 1
        shown = 0
        for h in rep.protected:
            s = f"・{h.from_addr}｜{' '.join(h.subject.split())[:60]}"
            if room - len(s) - 1 < _MORE_RESERVE:
                break
            lines.append(s)
            room -= len(s) + 1
            shown += 1
        if shown < len(rep.protected):
            lines.append(f"…還有 {len(rep.protected) - shown} 封")
    return discord.Embed(title="📬 每日信件整理", description="\n".join(lines)[:4096], color=COLOR)


def history_embed(plan: dict) -> discord.Embed:
    lines = [f"{_cat(cat)}｜{kind}｜{n} 封" for (cat, kind), n in sorted(plan.get("counts", {}).items())]
    for cat, subs in sorted(plan.get("samples", {}).items()):
        lines.append(f"　{_cat(cat)} 例：" + "、".join(s[:30] for s in subs[:3]))
    lines.append(f"待確認卡 {plan.get('pending_cards', 0)} 張｜未知 {plan.get('unknown', 0)} 封")
    e = discord.Embed(title="🗂 歷史信件整理計畫", description="\n".join(lines)[:4096], color=COLOR)
    e.set_footer(text="確認無誤再按「執行」")
    return e


def _guard_fail(interaction):
    return can_act(interaction.user.id, _owner_id())


async def _send_assign_cards(interaction, rejected: list[Rule]) -> None:
    """被拒絕的規則沒有建議類別可確認，每 4 條發一張手動指定卡（Discord 一則訊息最多 5 列元件）。"""
    for i in range(0, len(rejected), 4):
        chunk = rejected[i:i + 4]
        lines = "\n".join(f"`{r.sender}`｜{r.subject_pattern}" for r in chunk)
        await interaction.followup.send(f"這些被拒絕的樣式請手動指定類別：\n{lines}"[:2000],
                                        view=assign_view(chunk))


class RejectSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"mailrules:reject:(?P<card>[\w-]+)"):
    def __init__(self, card: str, options: list[discord.SelectOption]):
        super().__init__(discord.ui.Select(placeholder="勾選不要照建議的樣式", min_values=1,
                                           max_values=len(options), options=options,
                                           custom_id=f"mailrules:reject:{card}"))
        self.card = card

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        opts = [discord.SelectOption(label=o.label, value=o.value) for o in getattr(item, "options", [])]
        return cls(match["card"], opts or [discord.SelectOption(label="-", value="0")])

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        ids = [int(v) for v in (interaction.data or {}).get("values", [])]
        db = SessionLocal()
        try:
            repo.reject(db, self.card, ids)
            rules = repo.card_rules(db, self.card)
        finally:
            db.close()
        view = suggest_view(self.card, rules)
        await interaction.response.edit_message(embed=suggest_embed(self.card, rules, {}), view=view)
        if view is None:      # 卡上規則全被拒絕：沒有確認鈕了，直接發手動指定卡
            await _send_assign_cards(interaction, [r for r in rules if r.status == "rejected"])


class ConfirmButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mailrules:confirm:(?P<card>[\w-]+)"):
    def __init__(self, card: str):
        super().__init__(discord.ui.Button(label="✅ 確認", style=discord.ButtonStyle.success,
                                           custom_id=f"mailrules:confirm:{card}"))
        self.card = card

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["card"])

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        db = SessionLocal()
        try:
            repo.confirm_card(db, self.card, [])
            rules = repo.card_rules(db, self.card)
            rejected = [r for r in repo.rejected_rules(db) if r.card == self.card]
        finally:
            db.close()
        await interaction.response.edit_message(embed=suggest_embed(self.card, rules, {}), view=None)
        await interaction.followup.send(f"已確認（by {interaction.user.display_name}）")
        await _send_assign_cards(interaction, rejected)


class AssignSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"mailrules:assign:(?P<rid>\d+)"):
    def __init__(self, rid: int, label: str = ""):
        opts = [discord.SelectOption(label=name, value=key) for key, name in config.CATEGORIES]
        super().__init__(discord.ui.Select(placeholder=(label or f"規則 {rid}")[:144] + " → 選類別",
                                           min_values=1, max_values=1, options=opts,
                                           custom_id=f"mailrules:assign:{rid}"))
        self.rid = rid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["rid"]))

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        vals = (interaction.data or {}).get("values", [])
        if not vals or vals[0] not in config.LABELS:
            await interaction.response.send_message("⛔ 類別無效", ephemeral=True)
            return
        db = SessionLocal()
        try:
            repo.assign(db, self.rid, vals[0])
        finally:
            db.close()
        await interaction.response.send_message(f"規則 {self.rid} 已歸為『{_cat(vals[0])}』")


class ExecuteButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mailrules:exec:history"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="🚀 執行歷史整理", style=discord.ButtonStyle.danger,
                                           custom_id="mailrules:exec:history"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        # 歷史約萬封、逐封寫入會超過 15 分鐘：interaction token 屆時已過期，followup 發不出去。
        # 所以開始先把原訊息改成「執行中」，結束（或失敗）再用 bot 自己的權限編輯同一則訊息。
        running = discord.Embed(title="⏳ 歷史整理執行中", color=COLOR,
                                description="逐封處理中，完成後這則訊息會更新結果。")
        await interaction.response.edit_message(embed=running, view=None)
        from mailrules import run
        try:
            rep = await asyncio.to_thread(run.execute_history, _today())
            emb = daily_embed(rep)
            emb.title = "🗂 歷史整理完成"
        except Exception as e:
            emb = discord.Embed(title="❌ 歷史整理失敗", description=str(e)[:4000], color=_FAIL_COLOR)
        try:
            await interaction.message.edit(embed=emb, view=None)
        except Exception as e:
            print(f"⚠️ 歷史整理結果編輯訊息失敗：{e}")


def suggest_view(card: str, rules: list[Rule]) -> discord.ui.View | None:
    live = [r for r in rules if r.status == "suggested"]
    if not live:
        return None
    v = discord.ui.View(timeout=None)
    opts = [discord.SelectOption(label=f"{r.sender}｜{r.subject_pattern}"[:100], value=str(r.id))
            for r in live[:25]]
    v.add_item(RejectSelect(card, opts))
    v.add_item(ConfirmButton(card))
    return v


def assign_view(rules: list[Rule]) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for r in rules[:4]:
        v.add_item(AssignSelect(r.id, f"{r.sender}｜{r.subject_pattern}"))
    return v


def _post(embeds, make_view=None) -> None:
    chan = config.mail_channel_id()
    if chan:
        post_sync(chan, embeds, make_view=make_view)


def notify_daily(rep: RunReport) -> None:
    if not config.mail_channel_id():
        return
    # 每個 embed 各發一則：Discord 單則訊息 embed 文字合計上限 6000，合併發摘要多的日子會 400 整份消失
    _post([daily_embed(rep)])
    if rep.job_digest:
        _post([digest_embed("💼 今日職缺", rep.job_digest)])
    if rep.promo_digest:
        _post([digest_embed("🛍 本週推銷摘要", rep.promo_digest)])


def notify_cards(card_ids: list[str]) -> None:
    if not config.mail_channel_id() or not card_ids:
        return
    db = SessionLocal()
    try:
        cards = [(c, repo.card_rules(db, c)) for c in card_ids]
    finally:
        db.close()
    for card, rules in cards:
        _post([suggest_embed(card, rules, {})], make_view=lambda c=card, rs=rules: suggest_view(c, rs))


def notify_history_plan(plan: dict) -> None:
    _post([history_embed(plan)], make_view=lambda: _exec_view())


def _exec_view() -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(ExecuteButton())
    return v


def notify_failure(err: str) -> None:
    _post([discord.Embed(title="❌ 信件整理失敗", description=err[:4000], color=_FAIL_COLOR)])
