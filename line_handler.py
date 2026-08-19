import os
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

from core import process_text_message, handle_image

# LINE 憑證缺任一個就整個停用，而不是在 import 期炸掉。
# 舊寫法 `LineBotApi(os.getenv(...))` 在 token 為 None 時會 TypeError（SDK 直接把 token
# 串進 Authorization header）→ **import 崩潰 = 全站掛**：webhook、Discord Bot、PWA 一起沒。
# Discord 那邊本來就有 `if discord_token:` 守著，這裡補齊同樣的可選性。
_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_ENABLED = bool(_ACCESS_TOKEN and _CHANNEL_SECRET)

line_bot_api = LineBotApi(_ACCESS_TOKEN) if LINE_ENABLED else None
handler = WebhookHandler(_CHANNEL_SECRET) if LINE_ENABLED else None

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")


def register_line_routes(app: FastAPI):
    """將 LINE webhook 路由掛載到 FastAPI app 上（未設定憑證則整段跳過）"""
    if not LINE_ENABLED:
        print("ℹ️ 未設定 LINE_CHANNEL_ACCESS_TOKEN / LINE_CHANNEL_SECRET，跳過 LINE webhook")
        return

    # handler 在 import 期可能是 None，所以事件註冊不能用 module 層的 @handler.add 裝飾器
    handler.add(MessageEvent, message=TextMessage)(handle_message)
    handler.add(MessageEvent, message=ImageMessage)(handle_image_message)

    @app.post("/callback")
    async def callback(request: Request):
        signature = request.headers.get("X-Line-Signature")
        body = await request.body()
        try:
            handler.handle(body.decode("utf-8"), signature)
        except InvalidSignatureError:
            raise HTTPException(status_code=400, detail="Invalid signature")
        return "OK"


def _reply(event, messages: list[str]):
    """將字串列表轉為 LINE TextSendMessage 並回覆"""
    line_bot_api.reply_message(
        event.reply_token,
        [TextSendMessage(text=m) for m in messages]
    )


def handle_message(event):
    msg = event.message.text.strip()
    result = process_text_message(msg, user_id=event.source.user_id, base_url=BASE_URL,
                                 source="line")
    if result:
        _reply(event, result)


def handle_image_message(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b""
        for chunk in message_content.iter_content():
            image_bytes += chunk

        result = handle_image(image_bytes, source="line")
        _reply(event, result)
    except Exception as e:
        _reply(event, [f"💥 視覺大腦處理失敗：{str(e)}"])
