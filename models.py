from sqlalchemy import Column, Integer, String, DateTime, Date, Float, ForeignKey, func
from database import Base

class Transaction(Base):
    """支出紀錄表"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    item = Column(String, index=True)
    price = Column(Integer)
    category = Column(String, nullable=True, index=True)  # AI 自動分類欄位
    invoice_no = Column(String, nullable=True, index=True)  # 發票號碼，einvoice 自動帶入；手動記帳為 NULL
    created_at = Column(DateTime, default=func.now())


class Income(Base):
    """收入紀錄表"""
    __tablename__ = "incomes"

    id = Column(Integer, primary_key=True, index=True)
    item = Column(String, index=True)
    amount = Column(Integer)
    category = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())


class RecurringRecord(Base):
    """固定收支紀錄表"""
    __tablename__ = "recurring_records"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)          # "expense" or "income"
    item = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    category = Column(String, nullable=True)
    day_of_month = Column(Integer, nullable=False)  # 每月幾號 (1-28)
    active = Column(Integer, default=1)             # 1=啟用, 0=停用
    created_at = Column(DateTime, default=func.now())


class FoodPlace(Base):
    """美食地圖：想去/去過的店家"""
    __tablename__ = "food_places"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)                       # 正式店名（Places 正名）
    address = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    place_id = Column(String, unique=True, index=True)      # Google Place 唯一 ID（去重）
    country = Column(String, index=True, nullable=True)
    city = Column(String, index=True, nullable=True)        # 台灣=縣市，國外=城市，可空
    district = Column(String, nullable=True)
    cuisine_type = Column(String, nullable=True, index=True)
    recommended_items = Column(String, nullable=True)
    caution_summary = Column(String, nullable=True)         # 雷點摘要（後續階段才填）
    status = Column(String, default="想去", index=True)      # 想去 / 去過
    my_rating = Column(Integer, nullable=True)              # 共用評分 1-5
    my_note = Column(String, nullable=True)                # 共用心得
    source_url = Column(String, nullable=True)
    discord_message_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Recipe(Base):
    """食譜收錄：一道菜 + 一個連結"""
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)                       # 乾淨菜名（codex 清理後；可被 reply 改名）
    url = Column(String, unique=True, index=True)           # 原始連結（去重鍵）
    platform = Column(String, nullable=True)                # youtube/instagram/tiktok/facebook/threads/other（gmaps 在 ingest 被擋,不會入庫）
    discord_message_id = Column(String, nullable=True, index=True)  # 卡片訊息 ID（reply 改名回查）
    created_at = Column(DateTime, default=func.now())


class DeviceToken(Base):
    """PWA 長效裝置 token：用短效報表 token（邀請函）換發，存 DB 重啟不丟。

    無期限但記 last_used_at；要踢掉某台裝置就刪那列（auth.revoke_device_token）。
    """
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    label = Column(String, nullable=True)            # 哪台裝置（前端帶 userAgent 簡述）
    created_at = Column(DateTime, default=func.now())
    last_used_at = Column(DateTime, nullable=True)


class FoodPhoto(Base):
    """店家照片（一家店多張）：去過=自己拍的食物照。檔案存 media/，這裡只記相對路徑。"""
    __tablename__ = "food_photos"

    id = Column(Integer, primary_key=True, index=True)
    food_place_id = Column(Integer, ForeignKey("food_places.id", ondelete="CASCADE"),
                           index=True, nullable=False)  # 刪店時 DB 列自動清（檔案由 photos.delete_files_for_place 清）
    path = Column(String, nullable=False)                        # media 根目錄下的相對路徑
    source = Column(String, default="app")                       # app / bot（哪條路傳的）
    created_at = Column(DateTime, default=func.now())


class HistoryVideo(Base):
    """歷史教學影片：一支影片 + 一個連結。topic=主分類書架（一支一個）。"""
    __tablename__ = "history_videos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)                      # yt-dlp 標題，LLM 清乾淨；可被 reply 改名
    url = Column(String, unique=True, index=True)           # 原始連結（去重鍵）
    topic = Column(String, nullable=True, index=True)       # 主分類/書架
    channel = Column(String, nullable=True)                 # 講師/頻道名（yt-dlp uploader）
    platform = Column(String, nullable=True)                # youtube / other …
    discord_message_id = Column(String, nullable=True, index=True)  # 卡片訊息 ID（reply 編輯回查）
    created_at = Column(DateTime, default=func.now())


class VideoTag(Base):
    """影片標籤（去正規化多對多）：一支影片多個標籤，標籤直接存字串。"""
    __tablename__ = "video_tags"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("history_videos.id", ondelete="CASCADE"),
                      index=True, nullable=False)            # 刪影片時 DB 列自動清
    tag = Column(String, index=True, nullable=False)


class InvoiceSyncState(Base):
    """發票同步打卡高水位（單列，id 恆 = 1）。"""
    __tablename__ = "invoice_sync_state"

    id = Column(Integer, primary_key=True)             # 永遠 1
    last_covered_date = Column(Date, nullable=True)    # 已成功涵蓋到的最後一天（含）；NULL=尚未 bootstrap
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())