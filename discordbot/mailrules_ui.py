"""信件規則引擎的 Discord 端：建議確認卡、重視公司確認卡、每日報告、職缺／推銷摘要、歷史整理計畫卡。

元件用 DynamicItem：custom_id 自帶卡號／索引，bot 重啟後不需要記憶體狀態就能接手。只有本人能按。
建議確認卡是「每類一張整批核可卡」：以寄件者為單位拒絕／手動指定（規則仍是「寄件者＋主旨樣式」一條），
下拉的 value 是卡上寄件者依字母排序後的索引（card_senders）——卡上規則只改狀態不增減，索引不會變；
封數排序會變，不能當 value。重視公司卡的 value 同理用網域依字母排序後的索引（網域可能超過 100 字）。
確認卡上每個寄件者除了地址，還附顯示名稱與卡上樣式最近一封信的主旨（info＝repo.card_sender_info；查不到就只顯示地址）。
執行鈕的 custom_id 帶「計畫卡發出當下的最大卡號」與「已確認規則集合的指紋」：之後才長出的確認卡不擋執行，
但之後又確認卡／手動指定規則 → 計畫過期，要用 /信件計畫 重發。
確認卡與計畫卡都用 post_sync_wait 發：Discord 真的送出才記成已發（確認卡記在 mail_rules.posted_at、
重視公司卡記在 mail_valued_domains.posted_at、計畫卡記在 mail_state.plan_posted_card），沒發出去的下次會完整重發。
"""
import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from database import SessionLocal
from mailrules import config, repo
from mailrules.types import MailHeader, Rule, RunReport, ValuedDomain

from .bridge import post_sync, post_sync_wait

COLOR = 0x3498DB
_FAIL_COLOR = 0xE74C3C
_MORE_RESERVE = 30            # daily_embed 截斷時留給「…還有 N 封」的字數
CARD_LINES = 25               # 確認卡內文與「這些不是」下拉列幾個寄件者（Discord 下拉上限 25；其餘看名單）
_SENDER_CHARS = 60            # 卡上寄件者地址最多顯示幾個字
_INFO_SENDER_CHARS = 40       # 同上，但卡上附了顯示名稱與主旨時：每行變長，地址收短
_NAME_CHARS = 30              # 卡上寄件者顯示名稱最多顯示幾個字
_SUBJECT_CHARS = 50           # 卡上最近一封信的主旨最多顯示幾個字
_SUBJECT_PREFIX = "　└ "
_MD_ESCAPE = frozenset("\\*_~`|[]()<")      # Markdown 符號、遮罩連結 [..](..)、提及／表情／時間戳 <…> 的起手符號
_ASSIGN_PER_MSG = 4          # 手動指定下拉一則訊息最多幾個（Discord 一則訊息最多 5 列元件）
_FULL_LIST = "完整名單：/信件名單 層:你的規則，或手機 PWA 📬"


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


def card_senders(rules: list[Rule]) -> list[str]:
    """卡上所有寄件者依字母排序（不分狀態）：下拉 option 的 value 與手動指定的 custom_id 都用這裡的索引。"""
    return sorted({r.sender for r in rules})


def _sender_rows(rules: list[Rule], counts: dict) -> list[dict]:
    """每個寄件者一列，依封數由多到少（同封數依字母）。n＝封數（counts 空＝查不到 → None）；
    state：live＝還有待確認的、confirmed、rejected、assigned＝被拒絕後本人手動指定了類別。"""
    by: dict[str, list[Rule]] = {}
    for r in rules:
        by.setdefault(r.sender, []).append(r)
    out = []
    for i, sender in enumerate(card_senders(rules)):      # 索引與 callback 對回寄件者共用同一個函式
        rs = by[sender]
        manual = [r for r in rs if r.status == "confirmed" and r.suggested_by == "user"]
        if any(r.status == "suggested" for r in rs):
            state = "live"
        elif manual:
            state = "assigned"
        elif any(r.status == "confirmed" for r in rs):
            state = "confirmed"
        else:
            state = "rejected"
        n = sum(counts.get((r.sender, r.subject_pattern), 0) for r in rs) if counts else None
        out.append({"sender": sender, "idx": i, "patterns": len({r.subject_pattern for r in rs}), "n": n,
                    "state": state, "category": manual[0].category if manual else None})
    out.sort(key=lambda x: (-(x["n"] or 0), x["sender"]))
    return out


def _sender_text(x: dict, info: dict | None = None) -> str:
    """info＝{寄件者: {'name', 'subject'}}；省略或空＝只顯示地址。有顯示名稱放在地址前（粗體），
    最近一封的主旨另起一行。"""
    stats = f"｜{x['patterns']} 種主旨" + (f"｜{x['n']} 封" if x["n"] is not None else "")
    if not info:
        return f"`{_one_line(x['sender'], _SENDER_CHARS)}`{stats}"
    got = info.get(x["sender"]) or {}
    name, subject = _md(got.get("name"), _NAME_CHARS), _md(got.get("subject"), _SUBJECT_CHARS)
    head = (f"**{name}** " if name else "") + f"`{_one_line(x['sender'], _INFO_SENDER_CHARS)}`{stats}"
    return head + (f"\n{_SUBJECT_PREFIX}{subject}" if subject else "")


def _sender_line(x: dict, info: dict | None = None) -> str:
    if x["state"] == "rejected":
        return f"~~{_sender_text(x, info)}~~ 已拒絕"
    if x["state"] == "assigned":
        return f"~~{_sender_text(x, info)}~~ → {_cat(x['category'])}"
    return _sender_text(x, info)


def _card_status(rows: list[dict]) -> str:
    if any(x["state"] == "live" for x in rows):
        return "下拉勾不是這類的寄件者，其餘按「✅ 整類確認」"
    ok, rej, man = (sum(1 for x in rows if x["state"] == st) for st in ("confirmed", "rejected", "assigned"))
    if not ok:
        return "全部拒絕" + (f"（手動指定 {man} 個）" if man else "")
    return f"已確認 {ok} 個寄件者" + (f"、拒絕 {rej} 個" if rej else "") + (f"、手動指定 {man} 個" if man else "")


def _card_desc(rows: list[dict], counts: dict, info: dict | None) -> str:
    lines = [_sender_line(x, info) for x in rows[:CARD_LINES]]
    rest = rows[CARD_LINES:]
    if rest:
        more = f"（{sum(x['n'] for x in rest)} 封）" if counts else ""
        lines.append(f"…還有 {len(rest)} 個寄件者{more}，{_FULL_LIST}")
    return "\n".join(lines)


def suggest_embed(card: str, rules: list[Rule], counts: dict, info: dict | None = None) -> discord.Embed:
    """每類一張：標題「建議歸為『類別』：N 個寄件者、M 封」，內文依封數列前 CARD_LINES 個寄件者，其餘一行指向名單。
    封數查不到（counts 空）就整張不顯示封數。info（{寄件者: {'name', 'subject'}}）省略或空＝只顯示地址。"""
    rows = _sender_rows(rules, counts)
    cats = {r.category for r in rules if r.suggested_by != "user"} or {r.category for r in rules}
    head = f"🤖 建議歸為『{_cat(next(iter(cats)))}』" if len(cats) == 1 else "🤖 新寄件者分類建議"
    title = f"{head}：{len(rows)} 個寄件者" + (f"、{sum(x['n'] for x in rows)} 封" if counts else "")
    desc = _card_desc(rows, counts, info)
    if len(desc) > 4096 and info:      # 帶主旨太長：先去掉主旨，仍列滿 CARD_LINES 個寄件者
        desc = _card_desc(rows, counts, {k: {**v, "subject": ""} for k, v in info.items()})
    if len(desc) > 4096:      # 每行已截長，正常到不了；保險：整行丟掉，不留半行
        desc = desc[:4096].rsplit("\n", 1)[0]
    e = discord.Embed(title=title[:256], description=desc, color=COLOR)
    e.set_footer(text=f"信件整理 · {card} · {_card_status(rows)}")
    return e


def valued_embed(card: str, rows: list[ValuedDomain], counts: dict) -> discord.Embed:
    """每行「網域｜當初的主旨樣式｜封數」；封數查不到就不顯示。拒絕的劃掉；沒有待確認的＝最終狀態。"""
    lines = []
    for r in rows:
        n = counts.get(r.domain)
        s = f"{r.domain}｜{r.pattern or '—'}" + (f"｜{n} 封" if n is not None else "")
        lines.append(f"~~{s}~~ 已拒絕" if r.status == "rejected" else s)
    e = discord.Embed(title=f"🛡 新的重視公司：{len(rows)} 個網域", description="\n".join(lines)[:4096], color=COLOR)
    if any(r.status == "pending" for r in rows):
        status = "確認後這些網域寄來、沒有退訂連結的信都留收件匣；下拉勾不是的，再按「確認」"
    else:
        ok = sum(1 for r in rows if r.status == "confirmed")
        rej = sum(1 for r in rows if r.status == "rejected")
        status = (f"已確認 {ok} 個" + (f"、拒絕 {rej} 個" if rej else "")) if ok else "全部拒絕（沒有網域受保護）"
    e.set_footer(text=f"信件整理 · {card} · {status}")
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
        note = "沒移出、沒丟；求職往來另加「整理/求職」標籤" if rep.applied else "沒移出、沒丟"   # 沒執行就還沒加標籤
        lines.append(f"🛡 安全網的信都留在收件匣（{note}）：{len(rep.protected)} 封")
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
    lines.append(f"待確認卡 {plan.get('pending_cards', 0)} 張｜待確認重視公司 {plan.get('pending_valued', 0)} 個"
                 f"｜未知 {plan.get('unknown', 0)} 個樣式")
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


def _md(s: str | None, n: int) -> str:
    """同 _one_line，但輸出是 Markdown 內文：顯示名稱、主旨是外來文字，不能讓它改掉卡片排版、變成遮罩連結或 tag 人。
    @everyone／@here／@id 的 @ 後面插零寬空白；_MD_ESCAPE 的符號逐字加反斜線——不交給 discord.utils.escape_markdown：
    整串跳脫會在截斷處留下孤立的反斜線，逐字呼叫又看不到 [..](..) 這種多字元語法。n 是跳脫後的長度。"""
    text = discord.utils.escape_mentions(" ".join((s or "").split()))
    parts = ["\\" + c if c in _MD_ESCAPE else c for c in text]
    if sum(map(len, parts)) <= n:
        return "".join(parts)
    out, size = [], 0
    for p in parts:
        if size + len(p) > n - 1:
            break
        out.append(p)
        size += len(p)
    return "".join(out) + "…"


def _layer_line(kind: str, r: dict) -> str:
    if kind == "messages":
        d = r["date"][5:].replace("-", "/") if r.get("date") else "--/--"
        return (f"{d}｜{_one_line(r['sender'], 40)}｜{_one_line(r['subject'], 40)}"
                f"｜{r['where']}｜{r['next'] or '—'}")
    if kind == "domains":
        return f"{r['domain']}｜{r.get('status') or '—'}｜加入 {r['since'] or '--'}｜{r['count']} 封"
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


def _safe_info(db, card: str) -> dict:
    """寄件者顯示名稱與最近主旨只是輔助資訊：查不到就只顯示地址，不擋按鈕、不擋發卡。"""
    try:
        return repo.card_sender_info(db, card)
    except Exception as e:
        print(f"⚠️ 確認卡 {card} 寄件者資訊查詢失敗：{e}")
        return {}


def _safe_valued_counts(db, card: str) -> dict:
    try:
        return repo.valued_card_counts(db, card)
    except Exception as e:
        print(f"⚠️ 重視公司卡 {card} 封數查詢失敗：{e}")
        return {}


def _indices(values) -> list[int]:
    return [int(v) for v in values if str(v).isdigit()]


async def _send_assign_cards(interaction, card: str, rules: list[Rule], info: dict | None = None) -> None:
    """被拒絕的寄件者沒有建議類別可確認：每人一個「手動指定類別」下拉（整個寄件者在這張卡上被拒絕的樣式一起指定），
    每 _ASSIGN_PER_MSG 個一則訊息（Discord 一則訊息最多 5 列元件）。有 info 就附顯示名稱與最近一封主旨。"""
    senders = card_senders(rules)
    rej: dict[str, set] = {}
    for r in rules:
        if r.status == "rejected":
            rej.setdefault(r.sender, set()).add(r.subject_pattern)
    picks = [(senders.index(s), s) for s in sorted(rej)]
    for i in range(0, len(picks), _ASSIGN_PER_MSG):
        chunk = picks[i:i + _ASSIGN_PER_MSG]
        lines = "\n".join(_sender_text({"sender": s, "patterns": len(rej[s]), "n": None}, info) for _, s in chunk)
        # 內文帶外來的名稱與主旨，bot 又沒設全域 allowed_mentions：這則訊息自己關掉所有提及
        await interaction.followup.send(f"這些被拒絕的寄件者請手動指定類別（{card} 上這個寄件者的樣式一起指定）：\n{lines}"[:2000],
                                        view=assign_view(card, chunk, info),
                                        allowed_mentions=discord.AllowedMentions.none())


async def _rerender_card(interaction, card: str, rules: list[Rule], counts: dict, info: dict | None = None) -> None:
    view = suggest_view(card, rules, counts, info)
    await interaction.response.edit_message(embed=suggest_embed(card, rules, counts, info), view=view)
    if view is None:      # 卡上全被拒絕：沒有確認鈕了，直接發手動指定卡
        await _send_assign_cards(interaction, card, rules, info)


class SenderRejectSelect(discord.ui.DynamicItem[discord.ui.Select],
                         template=r"mailrules:rejsender:(?P<card>s\d+)"):
    """整批核可卡的「這些不是」：value＝寄件者在卡上的字母序索引；勾一個＝這個寄件者在卡上還待確認的樣式全部拒絕。"""
    def __init__(self, card: str, options: list[discord.SelectOption]):
        options = options or [discord.SelectOption(label="-", value="-")]
        super().__init__(discord.ui.Select(placeholder="勾選不是這類的寄件者", min_values=1,
                                           max_values=len(options), options=options,
                                           custom_id=f"mailrules:rejsender:{card}"))
        self.card = card

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        opts = [discord.SelectOption(label=o.label, value=o.value, description=o.description)
                for o in getattr(item, "options", [])]
        return cls(match["card"], opts)

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        idxs = _indices((interaction.data or {}).get("values", []))
        db = SessionLocal()
        try:
            senders = card_senders(repo.card_rules(db, self.card))
            repo.reject_senders(db, self.card, [senders[i] for i in idxs if i < len(senders)])
            rules = repo.card_rules(db, self.card)
            counts, info = _safe_counts(db, self.card), _safe_info(db, self.card)
        finally:
            db.close()
        await _rerender_card(interaction, self.card, rules, counts, info)


class RejectSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"mailrules:reject:(?P<card>[\w-]+)"):
    """逐條格式（每 25 條一張）確認卡的拒絕下拉，value＝規則 id；只讓已經發出去的這種卡還按得動，新卡不用。"""
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
        ids = _indices((interaction.data or {}).get("values", []))
        db = SessionLocal()
        try:
            repo.reject(db, self.card, ids)
            rules = repo.card_rules(db, self.card)
            counts, info = _safe_counts(db, self.card), _safe_info(db, self.card)
        finally:
            db.close()
        await _rerender_card(interaction, self.card, rules, counts, info)


class ConfirmButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mailrules:confirm:(?P<card>[\w-]+)"):
    """整類確認：卡上其餘還待確認的規則全部確認（新舊卡共用）。"""
    def __init__(self, card: str):
        super().__init__(discord.ui.Button(label="✅ 整類確認", style=discord.ButtonStyle.success,
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
            counts, info = _safe_counts(db, self.card), _safe_info(db, self.card)
        finally:
            db.close()
        await interaction.response.edit_message(embed=suggest_embed(self.card, rules, counts, info), view=None)
        await interaction.followup.send(f"已確認（by {interaction.user.display_name}）")
        await _send_assign_cards(interaction, self.card, rules, info)


def _assign_options() -> list[discord.SelectOption]:
    # 不提供「重要」「求職」：保護的信不走規則（安全網），手動指定只給會整理的類別
    return [discord.SelectOption(label=name, value=key) for key, name in config.CATEGORIES
            if key not in config.SAFETY_NET_ONLY]


def _valid_category(vals) -> str | None:
    return vals[0] if vals and vals[0] in config.LABELS and vals[0] not in config.SAFETY_NET_ONLY else None


class SenderAssignSelect(discord.ui.DynamicItem[discord.ui.Select],
                         template=r"mailrules:assignsender:(?P<card>s\d+):(?P<idx>\d+)"):
    """被拒絕的寄件者手動指定類別；idx＝寄件者在卡上的字母序索引（同 SenderRejectSelect）。"""
    def __init__(self, card: str, idx: int, label: str = ""):
        super().__init__(discord.ui.Select(placeholder=_one_line(label or f"寄件者 {idx}", 120) + " → 選類別",
                                           min_values=1, max_values=1, options=_assign_options(),
                                           custom_id=f"mailrules:assignsender:{card}:{idx}"))
        self.card, self.idx = card, idx

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["card"], int(match["idx"]))

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        cat = _valid_category((interaction.data or {}).get("values", []))
        if cat is None:
            await interaction.response.send_message("⛔ 類別無效", ephemeral=True)
            return
        db = SessionLocal()
        try:
            senders = card_senders(repo.card_rules(db, self.card))
            sender = senders[self.idx] if self.idx < len(senders) else None
            n = repo.assign_sender(db, self.card, sender, cat) if sender else 0
        finally:
            db.close()
        if sender is None:
            await interaction.response.send_message(f"⛔ {self.card} 上找不到這個寄件者", ephemeral=True)
            return
        await interaction.response.send_message(
            f"`{_one_line(sender, _SENDER_CHARS)}` 在 {self.card} 上的 {n} 個樣式已歸為『{_cat(cat)}』")


class AssignSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"mailrules:assign:(?P<rid>\d+)"):
    """逐條手動指定（value＝規則 id）；只讓已經發出去的這種訊息還按得動，新卡用 SenderAssignSelect。"""
    def __init__(self, rid: int, label: str = ""):
        super().__init__(discord.ui.Select(placeholder=(label or f"規則 {rid}")[:144] + " → 選類別",
                                           min_values=1, max_values=1, options=_assign_options(),
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
        cat = _valid_category((interaction.data or {}).get("values", []))
        if cat is None:
            await interaction.response.send_message("⛔ 類別無效", ephemeral=True)
            return
        db = SessionLocal()
        try:
            repo.assign(db, self.rid, cat)
        finally:
            db.close()
        await interaction.response.send_message(f"規則 {self.rid} 已歸為『{_cat(cat)}』")


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
        except run.PendingCards as e:
            # 擋下來的卡可能根本沒發出去過（頻道沒設、bot 沒 ready）：當場補發。post_sync_wait 會等 event loop，
            # 不能在 loop 上直接呼叫
            try:
                tail = await asyncio.to_thread(_repost_pending)
            except Exception as err:
                print(f"⚠️ 執行鈕補發確認卡失敗：{err}")
                tail = "❌ 補發確認卡時出錯，請稍後用 /信件計畫 重發"
            emb = discord.Embed(title="⏸ 還有待確認的卡，歷史整理沒有執行", description=f"{e}\n{tail}"[:4000],
                                color=_FAIL_COLOR)
            view = _exec_view(self.upto, self.fp)
        except Exception as e:
            emb = discord.Embed(title="❌ 歷史整理失敗", description=str(e)[:4000], color=_FAIL_COLOR)
            view = _exec_view(self.upto, self.fp)          # 處理完再按一次：同一顆鈕要留著
        try:
            await interaction.message.edit(embed=emb, view=view)
        except Exception as e:
            print(f"⚠️ 歷史整理結果編輯訊息失敗：{e}")


class ValuedRejectSelect(discord.ui.DynamicItem[discord.ui.Select],
                         template=r"mailrules:vreject:(?P<card>v\d+)"):
    """重視公司卡：下拉多選「這些不是重視的公司」（value＝網域在卡上依字母排序的索引；舊卡的 value 是網域本身，照收）。"""
    def __init__(self, card: str, options: list[discord.SelectOption]):
        options = options or [discord.SelectOption(label="-", value="-")]
        super().__init__(discord.ui.Select(placeholder="這些不是重視的公司", min_values=1,
                                           max_values=len(options), options=options,
                                           custom_id=f"mailrules:vreject:{card}"))
        self.card = card

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        opts = [discord.SelectOption(label=o.label, value=o.value) for o in getattr(item, "options", [])]
        return cls(match["card"], opts)

    async def callback(self, interaction: discord.Interaction):
        why = _guard_fail(interaction)
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        vals = [v for v in (interaction.data or {}).get("values", []) if v != "-"]
        db = SessionLocal()
        try:
            doms = _valued_domains(repo.valued_card(db, self.card))
            picked = [doms[int(v)] if v.isdigit() else v for v in vals if not v.isdigit() or int(v) < len(doms)]
            repo.reject_valued(db, self.card, picked)
            rows = repo.valued_card(db, self.card)
            counts = _safe_valued_counts(db, self.card)
        finally:
            db.close()
        await interaction.response.edit_message(embed=valued_embed(self.card, rows, counts),
                                                view=valued_view(self.card, rows))


class ValuedConfirmButton(discord.ui.DynamicItem[discord.ui.Button],
                          template=r"mailrules:vconfirm:(?P<card>v\d+)"):
    """重視公司卡：卡上仍待確認的網域全部確認（確認後才保護信；舊的歷史計畫卡因此過期）。"""
    def __init__(self, card: str):
        super().__init__(discord.ui.Button(label="✅ 確認", style=discord.ButtonStyle.success,
                                           custom_id=f"mailrules:vconfirm:{card}"))
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
            n = repo.confirm_valued_card(db, self.card)
            rows = repo.valued_card(db, self.card)
            counts = _safe_valued_counts(db, self.card)
        finally:
            db.close()
        await interaction.response.edit_message(embed=valued_embed(self.card, rows, counts), view=None)
        await interaction.followup.send(f"已確認 {n} 個重視公司（by {interaction.user.display_name}）")


def _valued_domains(rows: list[ValuedDomain]) -> list[str]:
    """卡上所有網域依字母排序（不分狀態）：下拉 option 的 value 用這裡的索引。"""
    return sorted(r.domain for r in rows)


def valued_view(card: str, rows: list[ValuedDomain]) -> discord.ui.View | None:
    live = [r for r in rows if r.status == "pending"]
    if not live:
        return None
    idx = {d: i for i, d in enumerate(_valued_domains(rows))}
    v = discord.ui.View(timeout=None)
    opts = [discord.SelectOption(label=_one_line(r.domain, 100), value=str(idx[r.domain])) for r in live[:25]]
    v.add_item(ValuedRejectSelect(card, opts))
    v.add_item(ValuedConfirmButton(card))
    return v


def _reject_option(x: dict, info: dict | None) -> discord.SelectOption:
    """label＝顯示名稱（沒有就地址），description＝「地址｜最近主旨」；沒有這個寄件者的 info 就寫樣式數與封數。
    value＝字母序索引，與 info 無關。"""
    got = (info or {}).get(x["sender"])
    if got is None:
        desc = f"{x['patterns']} 種主旨" + (f"｜{x['n']} 封" if x["n"] is not None else "")
        return discord.SelectOption(label=_one_line(x["sender"], 100), value=str(x["idx"]),
                                    description=_one_line(desc, 100))
    name = _one_line(got.get("name"), 100)
    parts = (_one_line(x["sender"], _INFO_SENDER_CHARS), _one_line(got.get("subject"), _SUBJECT_CHARS))
    return discord.SelectOption(label=name or _one_line(x["sender"], 100), value=str(x["idx"]),
                                description=_one_line("｜".join(p for p in parts if p), 100))


def suggest_view(card: str, rules: list[Rule], counts: dict | None = None,
                 info: dict | None = None) -> discord.ui.View | None:
    """「這些不是」下拉只列封數最多的 CARD_LINES 個還待確認的寄件者；value＝字母序索引。"""
    live = [x for x in _sender_rows(rules, counts or {}) if x["state"] == "live"]
    if not live:
        return None
    v = discord.ui.View(timeout=None)
    opts = [_reject_option(x, info) for x in live[:CARD_LINES]]
    v.add_item(SenderRejectSelect(card, opts))
    v.add_item(ConfirmButton(card))
    return v


def assign_view(card: str, picks: list[tuple[int, str]], info: dict | None = None) -> discord.ui.View:
    """picks＝[(寄件者字母序索引, 寄件者)]，最多 _ASSIGN_PER_MSG 個。有顯示名稱的 placeholder 寫「顯示名稱 地址」。"""
    v = discord.ui.View(timeout=None)
    for idx, sender in picks[:_ASSIGN_PER_MSG]:
        name = _one_line(((info or {}).get(sender) or {}).get("name"), _NAME_CHARS)
        v.add_item(SenderAssignSelect(card, idx, f"{name} {sender}" if name else sender))
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
        return repo.card_rules(db, card), _safe_counts(db, card), _safe_info(db, card)
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
            rules, counts, info = _card_payload(card)
            ok = _post_wait([suggest_embed(card, rules, counts, info)],
                            make_view=lambda c=card, rs=rules, cn=counts, inf=info: suggest_view(c, rs, cn, inf))
            if ok:
                _mark_posted([card])
                sent.append(card)
        except Exception as e:                   # 一張卡出事不擋其他卡；沒記已發 → 下次再發
            print(f"⚠️ 確認卡 {card} 發送或記錄已發失敗：{type(e).__name__}: {e}")
    return sent


def _valued_payload(card: str):
    db = SessionLocal()
    try:
        return repo.valued_card(db, card), _safe_valued_counts(db, card)
    finally:
        db.close()


def _mark_valued_posted(cards: list[str]) -> None:
    db = SessionLocal()
    try:
        repo.mark_valued_posted(db, cards)
    finally:
        db.close()


def notify_valued_cards(card_ids: list[str]) -> list[str]:
    """完整發重視公司確認卡；回傳真的送出的卡號，並在 DB 記已發（沒送出的不記，下次再完整發）。"""
    if not config.mail_channel_id() or not card_ids:
        return []
    sent = []
    for card in card_ids:
        try:
            rows, counts = _valued_payload(card)
            ok = _post_wait([valued_embed(card, rows, counts)],
                            make_view=lambda c=card, rs=rows: valued_view(c, rs))
            if ok:
                _mark_valued_posted([card])
                sent.append(card)
        except Exception as e:                   # 一張卡出事不擋其他卡；沒記已發 → 下次再發
            print(f"⚠️ 重視公司卡 {card} 發送或記錄已發失敗：{type(e).__name__}: {e}")
    return sent


def _unposted_all() -> tuple[list[str], list[str]]:
    """（還沒成功發過的規則確認卡, 還沒成功發過的重視公司卡）。"""
    db = SessionLocal()
    try:
        return repo.unposted_cards(db), repo.unposted_valued_cards(db)
    finally:
        db.close()


def _post_unposted() -> tuple[list[str], list[str]]:
    """兩種卡都完整補發；回傳（想發的, 真的送出的）。"""
    want, vwant = _unposted_all()
    return want + vwant, notify_cards(want) + notify_valued_cards(vwant)


def post_unposted_cards() -> list[str]:
    """還沒成功發出過的待確認卡（規則確認卡＋重視公司卡）完整發
    （每日排程出錯時也呼叫：出錯前已存進 DB 的新卡不會被吞掉）。"""
    if not config.mail_channel_id():
        return []
    return _post_unposted()[1]


def _repost_notes(want: list[str], sent: list[str]) -> list[str]:
    lost = [c for c in want if c not in sent]
    notes = []
    if sent:
        notes.append(f"補發確認卡 {'、'.join(sent)}")
    if lost:
        notes.append(f"❌ 確認卡 {'、'.join(lost)} 發送失敗，下次再試")
    return notes


def _repost_pending() -> str:
    """執行鈕被待確認擋下時補發還沒發出的卡（要在 event loop 外呼叫）；回傳如實的說明：
    該發哪些、真的送出哪些、哪些沒送出去。"""
    if not config.mail_channel_id():
        return "⚠️ 還沒設定 MAIL_CHANNEL_ID，待確認的卡發不出去"
    want, sent = _post_unposted()
    if not want:
        return "待確認的卡都發過了，請先到信件頻道處理；找不到卡可用 /信件計畫 重發"
    return "；".join(_repost_notes(want, sent)) + "；處理完再用 /信件計畫 重發計畫卡"


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
    """每日整理後：還沒成功發出過的待確認卡（規則確認卡＋重視公司卡）完整發、已發過的舊卡併成一行提醒
    （看 DB，不靠 rep.new_cards）；歷史未完成、沒有待確認卡、沒有待確認的重視網域、
    且目前已確認規則＋網域的計畫還沒成功發過 → 自動發歷史計畫卡。頻道沒設什麼都不發。"""
    if rep.skipped or not config.mail_channel_id():
        return
    db = SessionLocal()
    try:
        pending, fresh = repo.pending_cards(db), repo.unposted_cards(db)
        vpending, vfresh = repo.pending_valued_cards(db), repo.unposted_valued_cards(db)
        nvalued = repo.pending_valued_count(db)
        state = repo.get_state(db)
        posted, fp = repo.plan_posted_card(db), repo.confirmed_fingerprint(db)
    finally:
        db.close()
    notify_cards(fresh)
    notify_valued_cards(vfresh)
    notify_card_reminder([c for c in pending if c not in fresh] + [c for c in vpending if c not in vfresh])
    if pending or nvalued or state is None or state[2] is not None or posted == fp:
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
    """/信件計畫：隨時把目前的計畫卡發到信件頻道（發過也照發），並順便完整重發還沒成功發出過的待確認卡
    （規則確認卡＋重視公司卡；歷史整理已完成時也照補發，只是不發計畫卡）。
    回傳給下指令的人看的訊息；發送失敗如實說、不記已發。"""
    if not config.mail_channel_id():
        return "⚠️ 還沒設定 MAIL_CHANNEL_ID，發不出去"
    db = SessionLocal()
    try:
        state = repo.get_state(db)
    finally:
        db.close()
    if state is not None and state[2] is not None:
        notes = _repost_notes(*_post_unposted())
        return "歷史整理已完成，不需要計畫卡" + (("；" + "；".join(notes)) if notes else "")
    from mailrules import run
    try:
        plan = run.history_plan(today)
    except run.Busy:
        return "⏳ 另一個信件整理正在跑，請稍後再試"
    notes = _repost_notes(*_post_unposted())
    tail = ("；" + "；".join(notes)) if notes else ""
    if not _send_plan(plan):
        return "❌ 計畫卡發送失敗（Discord 沒回應或 bot 還沒 ready），沒有記成已發，請稍後再試" + tail
    return f"✅ 已發到信件頻道（待確認卡 {plan.get('pending_cards', 0)} 張）" + tail


def notify_failure(err: str) -> None:
    _post([discord.Embed(title="❌ 信件整理失敗", description=err[:4000], color=_FAIL_COLOR)])
