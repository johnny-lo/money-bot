import os
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

from core import process_text_message, handle_image

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

NGROK_DOMAIN = "your-ngrok-domain.ngrok-free.dev"
BASE_URL = f"https://{NGROK_DOMAIN}"


def register_line_routes(app: FastAPI):
    """將 LINE webhook 路由掛載到 FastAPI app 上"""

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


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    result = process_text_message(msg, user_id=event.source.user_id, base_url=BASE_URL)
    if result:
        _reply(event, result)


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b""
        for chunk in message_content.iter_content():
            image_bytes += chunk

        result = handle_image(image_bytes)
        _reply(event, result)
    except Exception as e:
        _reply(event, [f"💥 視覺大腦處理失敗：{str(e)}"])
