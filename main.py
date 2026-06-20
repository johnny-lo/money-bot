import os
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from sqlalchemy import inspect as sa_inspect

from database import engine, Base
from categorize import run_weekly_categorization
from recurring import run_daily_recurring
from einvoice import sync_invoices as run_invoice_sync
from invoice_backfill import sync_with_backfill
from routes.report import router as report_router
from routes.record import router as record_router
from routes.food_map import router as food_map_router
from routes.device import router as device_router
from routes.recipes import router as recipes_router
from routes.videos import router as videos_router
from line_handler import register_line_routes
from discordbot import (
    create_discord_bot,
    notify_invoice_sync,
    notify_invoice_failure,
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
        # food_photos 補 FK（既有表不會被 create_all 改結構）：先清孤兒列再加約束
        if _inspector.has_table("food_photos") and not _inspector.get_foreign_keys("food_photos"):
            _conn.execute(_text(
                "DELETE FROM food_photos WHERE food_place_id NOT IN (SELECT id FROM food_places)"
            ))
            _conn.execute(_text(
                "ALTER TABLE food_photos ADD CONSTRAINT fk_food_photos_place "
                "FOREIGN KEY (food_place_id) REFERENCES food_places(id) ON DELETE CASCADE"
            ))
            _conn.commit()
            print("✅ food_photos 已補上 FK（含孤兒清理）")
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
app.include_router(device_router)
app.include_router(recipes_router)
app.include_router(videos_router)
register_line_routes(app)

# 手機版 PWA（前端 build 後的靜態檔）；對外經 ngrok 走 /m/。沒 build 過則跳過（後端可獨立啟動）
if os.path.isdir("frontend/dist"):
    import mimetypes
    # Python 預設不認識 .webmanifest → 會用 text/plain 回，註冊正確的 MIME type
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    app.mount("/m", StaticFiles(directory="frontend/dist", html=True), name="mobile")

# 使用者上傳的店家照片（bot/app 兩條路都寫到 media/）
os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")

# -----------------------------------------------
# APScheduler：每週日 00:00 自動分類
# -----------------------------------------------
from apscheduler.schedulers.background import BackgroundScheduler


def _notify_invoice_result(result, *, quiet_if_empty=False):
    """全成功→成功摘要（quiet_if_empty 時 0 新增不發）；失敗→失敗卡。"""
    if not result["ok"]:
        notify_invoice_failure(result)
    elif result["new_items"] or not quiet_if_empty:
        notify_invoice_sync(result["summary"], result["new_items"])


def _daily_invoice_with_notify():
    """週一到週六 21:00 補拓同步後自動通知 Discord #🧾-發票通知 頻道。"""
    result = sync_with_backfill()
    _notify_invoice_result(result)


def _weekly_pipeline():
    """週日 21:00：發票同步 → AI 分類 → 週報 →（每月第一個週日多推上月月結）。"""
    try:
        result = sync_with_backfill()
        _notify_invoice_result(result)
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


def _startup_catchup():
    """開機後背景補拓一次（機器關了又開時盡快追上）；開機只在有新發票或失敗才發卡。"""
    result = sync_with_backfill()
    _notify_invoice_result(result, quiet_if_empty=True)


@app.on_event("startup")
async def startup_event():
    scheduler.start()
    scheduler.add_job(_startup_catchup, "date",
                      run_date=datetime.now() + timedelta(minutes=3), id="startup_catchup")
    print(
        "⏰ 排程已啟動："
        "每日 00:05 固定收支 / "
        "週一~週六 21:00 發票補拓+Discord 通知 / "
        "週日 21:00 補拓→分類→週報（每月第一個週日多推上月月結）/ "
        "開機後 3 分鐘背景發票補拓"
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
