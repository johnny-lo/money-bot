import os
import aiohttp
import discord
from discord import app_commands

from core import process_text_message, handle_image

NGROK_DOMAIN = "your-ngrok-domain.ngrok-free.dev"
BASE_URL = f"https://{NGROK_DOMAIN}"


class MoneyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f"🐉 Discord Bot 已上線：{self.user}")

    async def on_message(self, message: discord.Message):
        # 忽略自己的訊息
        if message.author == self.user:
            return

        # 處理圖片附件
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(attachment.url) as resp:
                                image_bytes = await resp.read()
                        result = handle_image(image_bytes)
                        for text in result:
                            await message.channel.send(text)
                    except Exception as e:
                        await message.channel.send(f"💥 視覺大腦處理失敗：{str(e)}")
                    return

        # 處理文字訊息
        msg = message.content.strip()
        if not msg:
            return

        result = process_text_message(
            msg,
            user_id=str(message.author.id),
            base_url=BASE_URL,
        )
        if result:
            for text in result:
                await message.channel.send(text)


def create_discord_bot() -> MoneyBot:
    return MoneyBot()
