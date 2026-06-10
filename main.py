import os
import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from sqlalchemy import inspect as sa_inspect

from database import engine, Base
from categorize import run_weekly_categorization
from recurring import run_daily_recurring
from einvoice import sync_invoices as run_invoice_sync
from routes.report import router as report_router
from routes.record import router as record_router
from routes.food_map import router as food_map_router
from line_handler import register_line_routes
from discord_handler import (
    create_discord_bot,
    notify_invoice_sync,
    notify_monthly_summary,
    notify_weekly_summary,
)

load_dotenv()

# 自動建立資料表
Base.metadata.create_all(bind=engine)

# 自動補上 category / invoice_no 欄位（已存在的資料庫不會自動加新欄）
try:
    from sqlalchemy import text as _text
    with engine.connect() as _conn:
        _inspector = sa_inspect(engine)
        _columns = [c["name"] for c in _inspector.get_columns("transactions")]
        if "category" not in _columns:
            _conn.execute(_text("ALTER TABLE transactions ADD COLUMN category VARCHAR"))
            _conn.commit()
            print("✅ 已自動新增 category 欄位")
        if "invoice_no" not in _columns:
            _conn.execute(_text("ALTER TABLE transactions ADD COLUMN invoice_no VARCHAR"))
            _conn.execute(_text(
                "CREATE INDEX IF NOT EXISTS ix_transactions_invoice_no ON transactions (invoice_no)"
            ))
            _conn.commit()
            print("✅ 已自動新增 invoice_no 欄位")
except Exception as e:
    print(f"⚠️ 欄位檢查/新增失敗：{e}")

# -----------------------------------------------
# FastAPI 應用程式
# -----------------------------------------------
app = FastAPI()

# 掛載路由
app.include_router(report_router)
app.include_router(record_router)
app.include_router(food_map_router)
register_line_routes(app)

# 手機版 PWA（前端 build 後的靜態檔）；對外經 ngrok 走 /m/。沒 build 過則跳過（後端可獨立啟動）
if os.path.isdir("frontend/dist"):
    app.mount("/m", StaticFiles(directory="frontend/dist", html=True), name="mobile")

# 使用者上傳的店家照片（bot/app 兩條路都寫到 media/）
os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")

# -----------------------------------------------
# APScheduler：每週日 00:00 自動分類
# -----------------------------------------------
from apscheduler.schedulers.background import BackgroundScheduler


def _daily_invoice_with_notify():
    """週一到週六 21:00 抓發票後自動通知 Discord #🧾-發票通知 頻道。"""
    result = run_invoice_sync(days=2)
    notify_invoice_sync(result["summary"], result.get("new_items", []))


def _weekly_pipeline():
    """週日 21:00：發票同步 → AI 分類 → 週報 →（每月第一個週日多推上月月結）。"""
    try:
        result = run_invoice_sync(days=2)
        notify_invoice_sync(result["summary"], result.get("new_items", []))
    except Exception as e:
        print(f"⚠️ 週日發票同步失敗：{e}")
    try:
        run_weekly_categorization()
    except Exception as e:
        print(f"⚠️ 週日分類失敗：{e}")
    try:
        notify_weekly_summary()
    except Exception as e:
        print(f"⚠️ 週報推送失敗：{e}")

    # 每月第一個週日（day ≤ 7）= 本月最早的週日 → 推上月完整月結
    from datetime import datetime as _dt
    if _dt.now().day <= 7:
        try:
            notify_monthly_summary()
        except Exception as e:
            print(f"⚠️ 月結推送失敗：{e}")


scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(run_daily_recurring, "cron", hour=0, minute=5, id="daily_recurring")
scheduler.add_job(
    _daily_invoice_with_notify, "cron",
    day_of_week="mon,tue,wed,thu,fri,sat", hour=21, minute=0,
    id="daily_invoice_sync",
)
scheduler.add_job(_weekly_pipeline, "cron", day_of_week="sun", hour=21, minute=0, id="weekly_pipeline")


@app.on_event("startup")
async def startup_event():
    scheduler.start()
    print(
        "⏰ 排程已啟動："
        "每日 00:05 固定收支 / "
        "週一~週六 21:00 抓發票+Discord 通知 / "
        "週日 21:00 抓發票→分類→週報（每月第一個週日多推上月月結）"
    )

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
