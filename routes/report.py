from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from models import Transaction, Income
from auth import validate_report_token, require_token

router = APIRouter()


@router.get("/api/report/monthly", dependencies=[Depends(require_token)])
def api_report_monthly(year: int = Query(None), month: int = Query(None), all: bool = Query(False),
                       db: Session = Depends(get_db)):
    """每日或每月支出/收入趨勢"""
    now = datetime.now()
    if all:
        # 全部月份：按月彙總
        expenses = db.query(
            func.extract('year', Transaction.created_at).label('y'),
            func.extract('month', Transaction.created_at).label('m'),
            func.sum(Transaction.price).label('total')
        ).group_by('y', 'm').order_by('y', 'm').all()

        incomes = db.query(
            func.extract('year', Income.created_at).label('y'),
            func.extract('month', Income.created_at).label('m'),
            func.sum(Income.amount).label('total')
        ).group_by('y', 'm').order_by('y', 'm').all()

        # 收集所有出現過的月份
        all_months = set()
        for r in expenses:
            all_months.add((int(r.y), int(r.m)))
        for r in incomes:
            all_months.add((int(r.y), int(r.m)))
        all_months = sorted(all_months)

        if not all_months:
            return {"mode": "all", "labels": [], "expenses": [], "incomes": []}

        labels = [f"{y}/{m:02d}" for y, m in all_months]
        expense_map = {(int(r.y), int(r.m)): int(r.total) for r in expenses}
        income_map = {(int(r.y), int(r.m)): int(r.total) for r in incomes}

        return {
            "mode": "all",
            "labels": labels,
            "expenses": [expense_map.get(k, 0) for k in all_months],
            "incomes": [income_map.get(k, 0) for k in all_months],
        }
    else:
        # 單月：按日彙總
        from calendar import monthrange
        y = year or now.year
        m = month or now.month
        days_in_month = monthrange(y, m)[1]

        expenses = db.query(
            func.extract('day', Transaction.created_at).label('day'),
            func.sum(Transaction.price).label('total')
        ).filter(
            func.extract('year', Transaction.created_at) == y,
            func.extract('month', Transaction.created_at) == m
        ).group_by('day').all()

        incomes = db.query(
            func.extract('day', Income.created_at).label('day'),
            func.sum(Income.amount).label('total')
        ).filter(
            func.extract('year', Income.created_at) == y,
            func.extract('month', Income.created_at) == m
        ).group_by('day').all()

        expense_map = {int(r.day): int(r.total) for r in expenses}
        income_map = {int(r.day): int(r.total) for r in incomes}

        days = list(range(1, days_in_month + 1))
        return {
            "mode": "month",
            "year": y, "month": m,
            "days": days,
            "expenses": [expense_map.get(d, 0) for d in days],
            "incomes": [income_map.get(d, 0) for d in days],
        }


@router.get("/api/report/category", dependencies=[Depends(require_token)])
def api_report_category(year: int = Query(None), month: int = Query(None), all: bool = Query(False),
                        db: Session = Depends(get_db)):
    """支出分類佔比（單月或全部）"""
    now = datetime.now()
    query = db.query(
        Transaction.category,
        func.sum(Transaction.price).label('total')
    )
    if not all:
        y = year or now.year
        m = month or now.month
        query = query.filter(
            func.extract('year', Transaction.created_at) == y,
            func.extract('month', Transaction.created_at) == m
        )
    results = query.group_by(Transaction.category).all()

    data = [
        {"name": r.category or "未分類", "value": int(r.total)}
        for r in results
    ]
    if all:
        return {"mode": "all", "data": data}
    return {"year": y, "month": m, "data": data}


@router.get("/api/report/summary", dependencies=[Depends(require_token)])
def api_report_summary(all: bool = Query(False), db: Session = Depends(get_db)):
    """收支總覽（近 6 個月或全部月份）"""
    if all:
        # 全部月份
        exp_rows = db.query(
            func.extract('year', Transaction.created_at).label('y'),
            func.extract('month', Transaction.created_at).label('m'),
            func.sum(Transaction.price).label('total')
        ).group_by('y', 'm').order_by('y', 'm').all()

        inc_rows = db.query(
            func.extract('year', Income.created_at).label('y'),
            func.extract('month', Income.created_at).label('m'),
            func.sum(Income.amount).label('total')
        ).group_by('y', 'm').order_by('y', 'm').all()

        all_months = set()
        for r in exp_rows:
            all_months.add((int(r.y), int(r.m)))
        for r in inc_rows:
            all_months.add((int(r.y), int(r.m)))
        all_months = sorted(all_months)

        expense_map = {(int(r.y), int(r.m)): int(r.total) for r in exp_rows}
        income_map = {(int(r.y), int(r.m)): int(r.total) for r in inc_rows}

        return {
            "months": [f"{y}/{m:02d}" for y, m in all_months],
            "expenses": [expense_map.get(k, 0) for k in all_months],
            "incomes": [income_map.get(k, 0) for k in all_months],
        }
    else:
        now = datetime.now()
        months = []
        expense_list = []
        income_list = []
        for i in range(5, -1, -1):
            target = now.month - i
            target_year = now.year
            while target <= 0:
                target += 12
                target_year -= 1

            label = f"{target_year}/{target:02d}"
            months.append(label)

            exp = db.query(func.sum(Transaction.price)).filter(
                func.extract('year', Transaction.created_at) == target_year,
                func.extract('month', Transaction.created_at) == target
            ).scalar() or 0
            inc = db.query(func.sum(Income.amount)).filter(
                func.extract('year', Income.created_at) == target_year,
                func.extract('month', Income.created_at) == target
            ).scalar() or 0

            expense_list.append(int(exp))
            income_list.append(int(inc))

        return {
            "months": months,
            "expenses": expense_list,
            "incomes": income_list,
        }


@router.get("/api/report/ledger", dependencies=[Depends(require_token)])
def api_report_ledger(year: int = Query(None), month: int = Query(None), all: bool = Query(False),
                      db: Session = Depends(get_db)):
    """流水帳：回傳所有收支明細"""
    now = datetime.now()
    exp_query = db.query(Transaction)
    inc_query = db.query(Income)
    if not all:
        y = year or now.year
        m = month or now.month
        exp_query = exp_query.filter(
            func.extract('year', Transaction.created_at) == y,
            func.extract('month', Transaction.created_at) == m
        )
        inc_query = inc_query.filter(
            func.extract('year', Income.created_at) == y,
            func.extract('month', Income.created_at) == m
        )

    expenses = exp_query.order_by(Transaction.created_at.desc()).all()
    incomes = inc_query.order_by(Income.created_at.desc()).all()

    records = []
    for r in expenses:
        records.append({
            "id": r.id,
            "type": "expense",
            "item": r.item,
            "amount": r.price,
            "category": r.category or "未分類",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        })
    for r in incomes:
        records.append({
            "id": r.id,
            "type": "income",
            "item": r.item,
            "amount": r.amount,
            "category": r.category or "未分類",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        })

    # 按時間降序排列
    records.sort(key=lambda x: x["created_at"], reverse=True)
    return {"records": records}


@router.get("/report", response_class=HTMLResponse)
def report_page(token: str = Query(None)):
    """互動式報表頁面（需要有效 token）"""
    if not token or not validate_report_token(token):
        raise HTTPException(status_code=401, detail="無效或過期的連結，請在 LINE Bot 傳送「報表」重新取得連結。")
    with open("templates/report.html", "r", encoding="utf-8") as f:
        return f.read()
