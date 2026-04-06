from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import SessionLocal
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


@router.post("/api/record", dependencies=[Depends(require_token)])
def api_create_record(body: RecordCreate):
    """新增一筆收支紀錄"""
    db = SessionLocal()
    try:
        if body.type == "income":
            record = Income(item=body.item, amount=body.amount, category=body.category)
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"id": record.id, "type": "income", "item": record.item,
                    "amount": record.amount, "category": record.category or "未分類",
                    "created_at": record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else ""}
        else:
            record = Transaction(item=body.item, price=body.amount, category=body.category)
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"id": record.id, "type": "expense", "item": record.item,
                    "amount": record.price, "category": record.category or "未分類",
                    "created_at": record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else ""}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/api/record/{record_type}/{record_id}", dependencies=[Depends(require_token)])
def api_update_record(record_type: str, record_id: int, body: RecordUpdate):
    """編輯一筆收支紀錄"""
    db = SessionLocal()
    try:
        if record_type == "income":
            record = db.query(Income).filter(Income.id == record_id).first()
            if not record:
                raise HTTPException(status_code=404, detail="找不到該收入紀錄")
            if body.item is not None:
                record.item = body.item
            if body.amount is not None:
                record.amount = body.amount
            if body.category is not None:
                record.category = body.category
            db.commit()
            db.refresh(record)
            return {"id": record.id, "type": "income", "item": record.item,
                    "amount": record.amount, "category": record.category or "未分類",
                    "created_at": record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else ""}
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
            return {"id": record.id, "type": "expense", "item": record.item,
                    "amount": record.price, "category": record.category or "未分類",
                    "created_at": record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else ""}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/api/record/{record_type}/{record_id}", dependencies=[Depends(require_token)])
def api_delete_record(record_type: str, record_id: int):
    """刪除一筆收支紀錄"""
    db = SessionLocal()
    try:
        if record_type == "income":
            record = db.query(Income).filter(Income.id == record_id).first()
            if not record:
                raise HTTPException(status_code=404, detail="找不到該收入紀錄")
            db.delete(record)
            db.commit()
            return {"message": f"已刪除收入 ID: {record_id}"}
        else:
            record = db.query(Transaction).filter(Transaction.id == record_id).first()
            if not record:
                raise HTTPException(status_code=404, detail="找不到該支出紀錄")
            db.delete(record)
            db.commit()
            return {"message": f"已刪除支出 ID: {record_id}"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
