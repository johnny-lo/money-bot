"""自動修復的 Discord 端：報告卡按鈕（只限本人）與 outbox 輪詢。

DB 只有容器寫：主機（run.sh / deploy.sh）把結果丟進 autofix/outbox/，這裡發卡並轉換事件狀態。
按鈕用 DynamicItem：custom_id 自帶事件 id，bot 重啟後不需要記憶體狀態就能接手。
"""
import json
import os
from datetime import datetime, timedelta

import discord

from autofix import incidents
from .embeds import autofix_report_embed, autofix_deploy_embed, autofix_escalated_embed

APPROVAL_TTL = timedelta(days=7)


def _dir(name: str) -> str:
    return os.path.join(os.getenv("AUTOFIX_DIR", "/app/autofix"), name)


def _owner_id() -> int | None:
    v = os.getenv("AUTOFIX_OWNER_USER_ID", "").strip()
    return int(v) if v.isdigit() else None


def can_act(user_id, owner_id, status, reported_at, now) -> str | None:
    if owner_id is None:
        return "還沒設定 AUTOFIX_OWNER_USER_ID，沒有人能部署"
    if user_id != owner_id:
        return "只有管理者能按這顆鈕"
    if status is None:
        return "找不到這個事件"
    if status != "reported":
        return f"這個事件目前是 {status}，不能再操作"
    if reported_at is None or now - reported_at > APPROVAL_TTL:
        return "核可已過期（超過 7 天），請開 session 重新處理"
    return None


def write_approval(incident_id: int, action: str) -> None:
    path = os.path.join(_dir("approved"), f"{incident_id}.{action}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(incidents.now_tw().isoformat())


class AutofixButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"autofix:(?P<action>deploy|abandon):(?P<id>\d+)"):
    def __init__(self, action: str, incident_id: int):
        label, style = (("✅ 部署", discord.ButtonStyle.success) if action == "deploy"
                        else ("❌ 放棄", discord.ButtonStyle.secondary))
        super().__init__(discord.ui.Button(label=label, style=style,
                                           custom_id=f"autofix:{action}:{incident_id}"))
        self.action, self.incident_id = action, incident_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction: discord.Interaction):
        inc = incidents.get(self.incident_id) or {}
        why = can_act(interaction.user.id, _owner_id(), inc.get("status"),
                      inc.get("reported_at"), incidents.now_tw())
        if why:
            await interaction.response.send_message(f"⛔ {why}", ephemeral=True)
            return
        if self.action == "deploy":
            incidents.mark(self.incident_id, "deploying")
            write_approval(self.incident_id, "deploy")
            note = "🚀 部署中…合併 → 測試 → 重啟 → 上線驗證，結果會回在這張卡底下"
        else:
            incidents.mark(self.incident_id, "abandoned", closed_at=incidents.now_tw())
            write_approval(self.incident_id, "abandon")
            note = "已放棄，修正分支會被清掉"
        await interaction.response.edit_message(view=None)   # 收掉按鈕，避免按第二次
        await interaction.followup.send(f"{note}（by {interaction.user.display_name}）")


def autofix_view(incident_id: int) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(AutofixButton("deploy", incident_id))
    v.add_item(AutofixButton("abandon", incident_id))
    return v


async def _handle(bot, ch, msg: dict) -> None:
    iid = int(msg["incident_id"])
    now = incidents.now_tw()
    if msg["type"] == "report":
        verdict = (msg.get("report") or {}).get("verdict")
        kw = {"embed": autofix_report_embed(msg)}
        if verdict == "fixed":
            kw["view"] = autofix_view(iid)
        diff = msg.get("diff_file")
        if diff and os.path.exists(os.path.join("/app", diff)):
            kw["file"] = discord.File(os.path.join("/app", diff), filename=f"autofix-{iid}.diff")
        sent = await ch.send(**kw)
        if verdict == "fixed":
            incidents.mark(iid, "reported", verdict=verdict, reported_at=now,
                           report_message_id=str(sent.id))
        else:
            incidents.mark(iid, verdict or "inconclusive", verdict=verdict, reported_at=now,
                           report_message_id=str(sent.id), closed_at=now)
    elif msg["type"] == "deploy":
        inc = incidents.get(iid) or {}
        embed = autofix_deploy_embed(msg)
        mid = inc.get("report_message_id")
        if mid:
            m = await ch.fetch_message(int(mid))
            await m.reply(embed=embed)
        else:
            await ch.send(embed=embed)
        st = msg["status"]
        if st == "reported":   # 前置檢查沒過：恢復按鈕讓使用者處理完再按
            incidents.mark(iid, "reported", reported_at=now)
            if mid:
                await ch.send(content=f"#{iid} 處理完可以再按一次：", view=autofix_view(iid))
        else:
            incidents.mark(iid, st, closed_at=now)
    elif msg["type"] == "escalated":
        await ch.send(embed=autofix_escalated_embed(msg))


_KIND_RANK = {"escalated": 0, "report": 0, "deploy": 1}


def _outbox_order(name: str) -> tuple:
    """`<id>-<kind>.json`：同一事件先報告卡、後部署結果（字母序 deploy 會排在 report 前面）。"""
    stem = name[:-5]
    iid, _, kind = stem.partition("-")
    return (int(iid) if iid.isdigit() else 0, _KIND_RANK.get(kind, 2), name)


async def process_outbox(bot) -> int:
    cid = os.getenv("AUTOFIX_CHANNEL_ID", "").strip()
    d = _dir("outbox")
    if not cid.isdigit() or not os.path.isdir(d):
        return 0
    ch = bot.get_channel(int(cid)) or await bot.fetch_channel(int(cid))
    n = 0
    for name in sorted((x for x in os.listdir(d) if x.endswith(".json")), key=_outbox_order):
        path = os.path.join(d, name)
        try:
            with open(path, encoding="utf-8") as f:
                msg = json.load(f)
            await _handle(bot, ch, msg)
            os.remove(path)
            n += 1
        except Exception as ex:
            print(f"⚠️ autofix outbox {name} 處理失敗：{type(ex).__name__}: {ex}", flush=True)
            os.replace(path, path + ".bad")   # 壞檔改名，別每 30 秒重試卡住佇列
    return n
