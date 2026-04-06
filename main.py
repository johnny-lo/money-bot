import os
import asyncio
from fastapi import FastAPI
from dotenv import load_dotenv
from sqlalchemy import inspect as sa_inspect

from database import engine, Base
from categorize import run_weekly_categorization
from recurring import run_daily_recurring
from routes.report import router as report_router
from routes.record import router as record_router
from line_handler import register_line_routes
from discord_handler import create_discord_bot

load_dotenv()

# 自動建立資料表
Base.metadata.create_all(bind=engine)

# 自動補上 category 欄位（已存在的資料庫不會自動加新欄）
try:
    from sqlalchemy import text as _text
    with engine.connect() as _conn:
        _inspector = sa_inspect(engine)
        _columns = [c["name"] for c in _inspector.get_columns("transactions")]
        if "category" not in _columns:
            _conn.execute(_text("ALTER TABLE transactions ADD COLUMN category VARCHAR"))
            _conn.commit()
            print("✅ 已自動新增 category 欄位")
except Exception as e:
    print(f"⚠️ category 欄位檢查/新增失敗：{e}")

# -----------------------------------------------
# FastAPI 應用程式
# -----------------------------------------------
app = FastAPI()

# 掛載路由
app.include_router(report_router)
app.include_router(record_router)
register_line_routes(app)

# -----------------------------------------------
# APScheduler：每週日 00:00 自動分類
# -----------------------------------------------
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(run_weekly_categorization, "cron", day_of_week="sun", hour=0, minute=0, id="weekly_categorize")
scheduler.add_job(run_daily_recurring, "cron", hour=0, minute=5, id="daily_recurring")


@app.on_event("startup")
async def startup_event():
    scheduler.start()
    print("⏰ 排程已啟動：每週日 00:00 自動分類 / 每日 00:05 固定收支")

    # 啟動 Discord Bot（如果有設定 token）
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    if discord_token:
        bot = create_discord_bot()
        asyncio.create_task(bot.start(discord_token))
        print("🎮 Discord Bot 啟動中...")
    else:
        print("ℹ️ 未設定 DISCORD_BOT_TOKEN，跳過 Discord Bot")


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
