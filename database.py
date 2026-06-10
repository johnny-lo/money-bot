import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 建立資料庫引擎
engine = create_engine(DATABASE_URL)

# 建立 Session 類別，供主程式實例化使用
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 宣告對應基準，給 models 使用
Base = declarative_base()


def get_db():
    """FastAPI dependency：yield 一個 session，請求結束自動 close。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """一般程式用的 context manager：成功 commit、例外 rollback、必 close。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()