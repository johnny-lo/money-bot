from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models import Transaction, Income
from auth import require_token

router = APIRouter()


class RecordCreate(BaseModel):
    type: str  # "expense" or "income"
    item: str
    amount: int
    category: Optional[str] = None


class RecordUpdate(BaseModel):
    item: Optional[str] = None
    amount: Optional[int] = None
    category: Optional[str] = None


def _record_dict(record, record_type: str) -> dict:
    amount = record.amount if record_type == "income" else record.price
    return {"id": record.id, "type": record_type, "item": record.item,
            "amount": amount, "category": record.category or "未分類",
            "created_at": record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else ""}


@router.post("/api/record", dependencies=[Depends(require_token)])
def api_create_record(body: RecordCreate, db: Session = Depends(get_db)):
    """新增一筆收支紀錄"""
    try:
        if body.type == "income":
            record = Income(item=body.item, amount=body.amount, category=body.category)
        else:
            record = Transaction(item=body.item, price=body.amount, category=body.category)
        db.add(record)
        db.commit()
        db.refresh(record)
        return _record_dict(record, "income" if body.type == "income" else "expense")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/record/{record_type}/{record_id}", dependencies=[Depends(require_token)])
def api_update_record(record_type: str, record_id: int, body: RecordUpdate,
                      db: Session = Depends(get_db)):
    """編輯一筆收支紀錄"""
    try:
        if record_type == "income":
            record = db.query(Income).filter(Income.id == record_id).first()
            if not record:
                raise HTTPException(status_code=404, detail="找不到該收入紀錄")
            if body.item is not None:
                record.item = body.item
            if body.amount is not None:
                record.amount = body.amount
        else:
            record = db.query(Transaction).filter(Transaction.id == record_id).first()
            if not record:
                raise HTTPException(status_code=404, detail="找不到該支出紀錄")
            if body.item is not None:
                record.item = body.item
            if body.amount is not None:
                record.price = body.amount
        if body.category is not None:
            record.category = body.category
        db.commit()
        db.refresh(record)
        return _record_dict(record, "income" if record_type == "income" else "expense")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/record/{record_type}/{record_id}", dependencies=[Depends(require_token)])
def api_delete_record(record_type: str, record_id: int, db: Session = Depends(get_db)):
    """刪除一筆收支紀錄"""
    try:
        if record_type == "income":
            record = db.query(Income).filter(Income.id == record_id).first()
            label = "收入"
        else:
            record = db.query(Transaction).filter(Transaction.id == record_id).first()
            label = "支出"
        if not record:
            raise HTTPException(status_code=404, detail=f"找不到該{label}紀錄")
        db.delete(record)
        db.commit()
        return {"message": f"已刪除{label} ID: {record_id}"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
