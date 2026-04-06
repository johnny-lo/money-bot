import os
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