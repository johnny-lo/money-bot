"""MoneyBot：Discord client 本體（事件路由）＋ create_discord_bot 工廠。"""
import os
import time

import discord
from discord import app_commands

from .bridge import set_bot
from .commands import register_commands
from . import ingest_handlers

# 非目標頻道圖片提示的防洗版：{channel_id: last_hint_ts}
_HINT_DEBOUNCE: dict[int, float] = {}
HINT_COOLDOWN_SEC = 1800  # 30 分鐘


class MoneyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        register_commands(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f"🐉 Discord Bot 已上線：{self.user}")

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return

        food_chan = os.getenv("FOOD_INGEST_CHANNEL_ID") or ""
        rec_chan = os.getenv("DISCORD_RECORD_CHANNEL_ID") or ""
        recipe_chan = os.getenv("RECIPE_INGEST_CHANNEL_ID") or ""
        ch_id = str(message.channel.id)

        # ── 1) 美食頻道：reply 補件 / 圖片或文字 ingest ─────────────
        if food_chan and ch_id == food_chan:
            await ingest_handlers.handle_food_message(message)
            return

        # ── 1.5) 食譜頻道：reply 改名/補名 / 連結 ingest ────────────
        if recipe_chan and ch_id == recipe_chan:
            await ingest_handlers.handle_recipe_message(message)
            return

        # ── 1.6) 歷史影片頻道：reply 編輯 / 連結 ingest / help ──────
        video_chan = os.getenv("HISTORY_VIDEO_INGEST_CHANNEL_ID") or ""
        if video_chan and ch_id == video_chan:
            await ingest_handlers.handle_video_message(message)
            return

        # ── 2) 圖片附件分流 ───────────────────────────────────────
        if message.attachments:
            images = [a for a in message.attachments
                      if a.content_type and a.content_type.startswith("image/")]
            if not images:
                return
            if not rec_chan:
                # 退路：未設記帳頻道 → 保留舊的「任意頻道圖片記帳」行為
                await ingest_handlers.do_image_recording(message, images[0])
                return
            if ch_id == rec_chan:
                await ingest_handlers.do_image_recording(message, images[0])
                return
            # 其他頻道：提示分流（含防洗版）
            now = time.time()
            last = _HINT_DEBOUNCE.get(message.channel.id, 0)
            if now - last >= HINT_COOLDOWN_SEC:
                _HINT_DEBOUNCE[message.channel.id] = now
                hint = "💡 記帳請丟 <#" + rec_chan + ">"
                if food_chan:
                    hint += "，記美食請丟 <#" + food_chan + ">"
                await message.channel.send(hint)
            return
        # 非圖片、非美食頻道訊息 → 不處理（讓 slash 自行運作）

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # 自己的反應不處理
        if payload.user_id == (self.user.id if self.user else 0):
            return
        food_chan = os.getenv("FOOD_INGEST_CHANNEL_ID") or ""
        if not food_chan or str(payload.channel_id) != food_chan:
            return
        if str(payload.emoji) != "✅":
            return
        from food.repo import set_visited_by_message_id
        rec = set_visited_by_message_id(payload.message_id)
        if rec is None:
            return
        ch = self.get_channel(payload.channel_id)
        if ch:
            await ch.send(
                f"🍜 已標記去過：**{rec['name']}**（編號 {rec['id']}）。"
                "想記評分/心得嗎？回我一句或用 `/去過`。"
            )


def create_discord_bot() -> MoneyBot:
    bot = MoneyBot()
    set_bot(bot)
    return bot
