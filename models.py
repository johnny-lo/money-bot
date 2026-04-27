from sqlalchemy import Column, Integer, String, DateTime, func
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