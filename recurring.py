from datetime import datetime
from database import SessionLocal
from models import RecurringRecord, Transaction, Income


def run_daily_recurring():
    """每日檢查並自動寫入當天到期的固定收支"""
    today = datetime.now().day
    db = SessionLocal()
    count = 0
    try:
        records = db.query(RecurringRecord).filter(
            RecurringRecord.active == 1,
            RecurringRecord.day_of_month == today,
        ).all()

        for r in records:
            if r.type == "income":
                entry = Income(item=r.item, amount=r.amount, category=r.category)
            else:
                entry = Transaction(item=r.item, price=r.amount, category=r.category)
            db.add(entry)
            count += 1

        if count:
            db.commit()
        print(f"[recurring] {datetime.now().strftime('%Y-%m-%d')} 自動記入 {count} 筆固定收支")
    except Exception as e:
        db.rollback()
        print(f"[recurring] 自動記帳失敗：{e}")
    finally:
        db.close()
    return count
