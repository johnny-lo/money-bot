"""信件規則引擎的 Discord 端：建議確認卡、每日報告、職缺／推銷摘要、歷史整理計畫卡。

元件用 DynamicItem：custom_id 自帶卡號／規則 id，bot 重啟後不需要記憶體狀態就能接手。只有本人能按。
執行鈕的 custom_id 帶「計畫卡發出當下的最大卡號」與「已確認規則集合的指紋」：之後才長出的確認卡不擋執行，
但之後又確認卡／手動指定規則 → 計畫過期，要用 /信件計畫 重發。
確認卡與計畫卡都用 post_sync_wait 發：Discord 真的送出才記成已發（確認卡記在 mail_rules.posted_at、
計畫卡記在 mail_state.plan_posted_card），沒發出去的下次會完整重發。
"""
import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from database import SessionLocal
from mailrules import config, repo
from mailrules.types import MailHeader, Rule, RunReport

from .bridge import post_sync, post_sync_wait

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
    if rep.skipped:
        return discord.Embed(title="📬 每日信件整理", description="⏭ 另一個信件整理正在跑，這次略過。", color=COLOR)
    lines = []
    if not rep.applied:
        lines.append("⏸ 歷史整理完成前只分類、不動信件。")
    for (cat, kind), n in sorted(rep.counts.items()):
        lines.append(f"{_cat(cat)}｜{kind}｜{n} 封")
    lines.append(f"❓ 未知樣式：{rep.unknown_patterns} 個")
    if rep.failed:
        lines.append(f"⚠️ 失敗：{rep.failed} 封")
    if rep.gone:
        lines.append(f"📭 已不在信箱 {rep.gone} 封（略過）")
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
    lines.append(f"待確認卡 {plan.get('pending_cards', 0)} 張｜未知 {plan.get('unknown', 0)} 個樣式")
    e = discord.Embed(title="🗂 歷史信件整理計畫", description="\n".join(lines)[:4096], color=COLOR)
    e.set_footer(text="確認無誤再按「執行」")
    return e


def overview_embed(layers: list[dict]) -> discord.Embed:
    if not any(x["count"] for x in layers):
        desc = "還沒同步過信件"
    else:
        desc = "\n".join(f"{x['title']}　{x['count']}" for x in layers)
    e = discord.Embed(title="📬 信件名單總覽", description=desc[:4096], color=COLOR)
    e.set_footer(text="用 /信件名單 層:… 看某一層的名單")
    return e


def _one_line(s: str | None, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _layer_line(kind: str, r: dict) -> str:
    if kind == "messages":
        d = r["date"][5:].replace("-", "/") if r.get("date") else "--/--"
        return (f"{d}｜{_one_line(r['sender'], 40)}｜{_one_line(r['subject'], 40)}"
                f"｜{r['where']}｜{r['next'] or '—'}")
    if kind == "domains":
        return f"{r['domain']}｜加入 {r['since'] or '--'}｜{r['count']} 封"
    if kind == "rules":
        return (f"{_one_line(r['sender'], 40)}｜{_one_line(r['pattern'], 40)}"
                f"｜→ {r['category']}｜{r['status']}")
    return f"{_one_line(r['sender'], 40)}｜{_one_line(r['pattern'], 40)}｜{r['count']} 封"


def layer_embed(data: dict, page: int, pages: int) -> discord.Embed:
    lines = [_layer_line(data["kind"], r) for r in data["rows"]] or ["這一層目前沒有符合的項目"]
    desc = "\n".join(lines)
    if len(desc) > 4096:      # 每行已截長，正常到不了；保險：整行丟掉，不留半行
        desc = desc[:4096].rsplit("\n", 1)[0]
    e = discord.Embed(title=f"📬 {data['title']}（共 {data['total']} 筆）", description=desc, color=COLOR)
    e.set_footer(text=f"第 {page}/{pages} 頁 · 完整名單在手機 PWA 📬 分頁")
    return e


def _guard_fail(interaction):
    return can_act(interaction.user.id, _owner_id())


def _safe_counts(db, card: str) -> dict:
    """封數只是輔助資訊：查不到就不顯示，不擋按鈕。"""
    try:
        return repo.card_counts(db, card)
    except Exception as e:
        print(f"⚠️ 確認卡 {card} 封數查詢失敗：{e}")
        return {}


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
            counts = _safe_counts(db, self.card)
        finally:
            db.close()
        view = suggest_view(self.card, rules)
        await interaction.response.edit_message(embed=suggest_embed(self.card, rules, counts), view=view)
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
            counts = _safe_counts(db, self.card)
        finally:
            db.close()
        await interaction.response.edit_message(embed=suggest_embed(self.card, rules, counts), view=None)
        await interaction.followup.send(f"已確認（by {interaction.user.display_name}）")
        await _send_assign_cards(interaction, rejected)


class AssignSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"mailrules:assign:(?P<rid>\d+)"):
    def __init__(self, rid: int, label: str = ""):
        # 不提供「重要」：保護的信不走規則（安全網），手動指定只給會整理的類別
        opts = [discord.SelectOption(label=name, value=key) for key, name in config.CATEGORIES if key != "keep_inbox"]
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
        if not vals or vals[0] not in config.LABELS or vals[0] == "keep_inbox":
            await interaction.response.send_message("⛔ 類別無效", ephemeral=True)
            return
        db = SessionLocal()
        try:
            repo.assign(db, self.rid, vals[0])
        finally:
            db.close()
        await interaction.response.send_message(f"規則 {self.rid} 已歸為『{_cat(vals[0])}』")


class ExecuteButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"mailrules:exec:history(?::(?P<card>s\d+|none))?(?::(?P<fp>[0-9a-f]+))?"):
    """upto＝計畫卡發出當下的最大卡號（'none'＝當時沒有卡）；fp＝當下已確認規則集合的指紋。
    沒帶指紋的鈕不知道核可的是哪一套規則 → 一律當計畫已過期，不執行。"""
    def __init__(self, upto: str | None = None, fp: str | None = None):
        cid = "mailrules:exec:history" + (f":{upto}" if upto else "") + (f":{fp}" if fp else "")
        super().__init__(discord.ui.Button(label="🚀 執行歷史整理", style=discord.ButtonStyle.danger, custom_id=cid))
        self.upto, self.fp = upto, fp

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["card"], match["fp"])

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        from mailrules import run
        if not self.fp:
            await interaction.response.send_message(f"⛔ {run._EXPIRED}", ephemeral=True)
            return
        # 歷史約萬封、逐封寫入會超過 15 分鐘：interaction token 屆時已過期，followup 發不出去。
        # 所以開始先把原訊息改成「執行中」，結束（或失敗）再用 bot 自己的權限編輯同一則訊息。
        running = discord.Embed(title="⏳ 歷史整理執行中", color=COLOR,
                                description="逐封處理中，完成後這則訊息會更新結果。\n"
                                            "若停在這裡，可用 /信件計畫 重發計畫卡")
        await interaction.response.edit_message(embed=running, view=None)
        try:
            rep = await asyncio.to_thread(run.execute_history, _today(), upto_card=self.upto, fingerprint=self.fp)
            emb = daily_embed(rep)
            emb.title = "🗂 歷史整理完成"
            view = None
        except Exception as e:
            emb = discord.Embed(title="❌ 歷史整理失敗", description=str(e)[:4000], color=_FAIL_COLOR)
            view = _exec_view(self.upto, self.fp)          # 處理完再按一次：同一顆鈕要留著
        try:
            await interaction.message.edit(embed=emb, view=view)
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
    """射後不理（每日報告、摘要、提醒、失敗卡）：沒送出也不用記。"""
    chan = config.mail_channel_id()
    if chan:
        post_sync(chan, embeds, make_view=make_view)


def _post_wait(embeds, make_view=None) -> bool:
    """等送出結果（確認卡、計畫卡）：真的送出才回 True，呼叫端據此記「已發」。"""
    chan = config.mail_channel_id()
    return bool(chan) and post_sync_wait(chan, embeds, make_view=make_view)


def notify_daily(rep: RunReport) -> None:
    if not config.mail_channel_id():
        return
    # 每個 embed 各發一則：Discord 單則訊息 embed 文字合計上限 6000，合併發摘要多的日子會 400 整份消失
    _post([daily_embed(rep)])
    if rep.job_digest:
        _post([digest_embed("💼 今日職缺", rep.job_digest)])
    if rep.promo_digest:
        _post([digest_embed("🛍 本週推銷摘要", rep.promo_digest)])


def _card_payload(card: str):
    db = SessionLocal()
    try:
        return repo.card_rules(db, card), _safe_counts(db, card)
    finally:
        db.close()


def _mark_posted(cards: list[str]) -> None:
    db = SessionLocal()
    try:
        repo.mark_cards_posted(db, cards)
    finally:
        db.close()


def notify_cards(card_ids: list[str]) -> list[str]:
    """完整發確認卡；回傳真的送出的卡號，並在 DB 記已發（沒送出的不記，下次再完整發）。"""
    if not config.mail_channel_id() or not card_ids:
        return []
    sent = []
    for card in card_ids:
        try:
            rules, counts = _card_payload(card)
            ok = _post_wait([suggest_embed(card, rules, counts)],
                            make_view=lambda c=card, rs=rules: suggest_view(c, rs))
            if ok:
                _mark_posted([card])
                sent.append(card)
        except Exception as e:                   # 一張卡出事不擋其他卡；沒記已發 → 下次再發
            print(f"⚠️ 確認卡 {card} 發送或記錄已發失敗：{type(e).__name__}: {e}")
    return sent


def post_unposted_cards() -> list[str]:
    """還沒成功發出過的待確認卡完整發（每日排程出錯時也呼叫：出錯前已存進 DB 的新卡不會被吞掉）。"""
    if not config.mail_channel_id():
        return []
    db = SessionLocal()
    try:
        cards = repo.unposted_cards(db)
    finally:
        db.close()
    return notify_cards(cards)


def notify_card_reminder(card_ids: list[str]) -> None:
    """已經發過、還沒處理的舊卡不重發整張，只發一行提醒。"""
    if not card_ids:
        return
    _post([discord.Embed(description=f"📝 還有 {len(card_ids)} 張確認卡沒處理：{'、'.join(card_ids)}",
                         color=COLOR)])


def notify_history_plan(plan: dict) -> bool:
    """發計畫卡；回傳是否真的送出。執行鈕帶發卡當下的最大卡號與已確認規則指紋。"""
    upto, fp = plan.get("upto_card") or "none", plan.get("fingerprint")
    return _post_wait([history_embed(plan)], make_view=lambda: _exec_view(upto, fp))


def _exec_view(upto: str | None, fp: str | None) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(ExecuteButton(upto, fp))
    return v


def _send_plan(plan: dict) -> bool:
    """發計畫卡；真的送出才把這份計畫的規則指紋記進 mail_state.plan_posted_card。"""
    if not notify_history_plan(plan):
        return False
    db = SessionLocal()
    try:
        repo.set_plan_posted(db, plan["fingerprint"])
    finally:
        db.close()
    return True


def after_daily(rep: RunReport, today) -> None:
    """每日整理後：還沒成功發出過的待確認卡完整發、已發過的舊卡一行提醒（看 DB，不靠 rep.new_cards）；
    歷史未完成、沒有待確認卡、且目前已確認規則集合的計畫還沒成功發過 → 自動發歷史計畫卡。頻道沒設什麼都不發。"""
    if rep.skipped or not config.mail_channel_id():
        return
    db = SessionLocal()
    try:
        pending, fresh = repo.pending_cards(db), repo.unposted_cards(db)
        state = repo.get_state(db)
        posted, fp = repo.plan_posted_card(db), repo.confirmed_fingerprint(db)
    finally:
        db.close()
    notify_cards(fresh)
    notify_card_reminder([c for c in pending if c not in fresh])
    if pending or state is None or state[2] is not None or posted == fp:
        return
    from mailrules import run
    try:
        plan = run.history_plan(today)
    except run.Busy:
        print("⚠️ 另一個信件整理正在跑，這次不發歷史計畫卡（下次每日再發）")
        return
    if not _send_plan(plan):
        print("⚠️ 歷史計畫卡沒發出去，沒記成已發（下次每日再發）")


def post_history_plan(today) -> str:
    """/信件計畫：隨時把目前的計畫卡發到信件頻道（發過也照發），並順便完整重發還沒成功發出過的待確認卡。
    回傳給下指令的人看的訊息；發送失敗如實說、不記已發。"""
    if not config.mail_channel_id():
        return "⚠️ 還沒設定 MAIL_CHANNEL_ID，發不出去"
    db = SessionLocal()
    try:
        state = repo.get_state(db)
    finally:
        db.close()
    if state is not None and state[2] is not None:
        return "歷史整理已完成，不需要計畫卡"
    from mailrules import run
    try:
        plan = run.history_plan(today)
    except run.Busy:
        return "⏳ 另一個信件整理正在跑，請稍後再試"
    db = SessionLocal()
    try:
        want = repo.unposted_cards(db)
    finally:
        db.close()
    sent = notify_cards(want)
    lost = [c for c in want if c not in sent]
    notes = []
    if sent:
        notes.append(f"補發確認卡 {'、'.join(sent)}")
    if lost:
        notes.append(f"❌ 確認卡 {'、'.join(lost)} 發送失敗，下次再試")
    tail = ("；" + "；".join(notes)) if notes else ""
    if not _send_plan(plan):
        return "❌ 計畫卡發送失敗（Discord 沒回應或 bot 還沒 ready），沒有記成已發，請稍後再試" + tail
    return f"✅ 已發到信件頻道（待確認卡 {plan.get('pending_cards', 0)} 張）" + tail


def notify_failure(err: str) -> None:
    _post([discord.Embed(title="❌ 信件整理失敗", description=err[:4000], color=_FAIL_COLOR)])
