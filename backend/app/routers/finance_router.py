"""Finance router — expenses, revenue, profit/loss, dashboard."""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, require_admin
from backend.app.schemas.finance import ExpenseCreate
from backend.app.services import finance_service

router = APIRouter(tags=["finance"])

finance_router = APIRouter(prefix="/finance")
revenue_router = APIRouter(prefix="/revenue")
dashboard_router = APIRouter(prefix="/dashboard")


# Dashboard
@dashboard_router.get("/stats")
def dashboard_stats(admin=Depends(require_admin), db: Session = Depends(get_db)):
    return finance_service.get_dashboard_stats(db)


@finance_router.get("/dashboard")
def finance_dashboard(admin=Depends(require_admin), db: Session = Depends(get_db)):
    return finance_service.get_dashboard_stats(db)


# Revenue
@revenue_router.get("/daily")
def daily_revenue(
    date_from: Optional[date] = Query(None), date_to: Optional[date] = Query(None),
    from_date: Optional[date] = Query(None, alias="from"), to_date: Optional[date] = Query(None, alias="to"),
    admin=Depends(require_admin), db: Session = Depends(get_db)
):
    f = date_from or from_date
    t = date_to or to_date
    if not t:
        t = date.today()
    if not f:
        f = t.replace(day=1)
    if f > t:
        raise HTTPException(status_code=400, detail="'from' date must be before or equal to 'to' date")
    return finance_service.get_daily_revenue(db, f, t)


@revenue_router.get("/monthly")
def monthly_revenue(
    year: int = Query(default=datetime.now().year),
    admin=Depends(require_admin), db: Session = Depends(get_db)
):
    return finance_service.get_monthly_revenue(db, year)


@revenue_router.get("/payment-split")
def payment_split(
    date_from: Optional[date] = Query(None), date_to: Optional[date] = Query(None),
    from_date: Optional[date] = Query(None, alias="from"), to_date: Optional[date] = Query(None, alias="to"),
    admin=Depends(require_admin), db: Session = Depends(get_db)
):
    f = date_from or from_date
    t = date_to or to_date
    if not t:
        t = date.today()
    if not f:
        f = t.replace(day=1)
    if f > t:
        raise HTTPException(status_code=400, detail="'from' date must be before or equal to 'to' date")
    return finance_service.get_payment_split(db, f, t)


# Expenses
@finance_router.post("/expenses", status_code=201)
def create_expense(payload: ExpenseCreate, admin=Depends(require_admin),
                   db: Session = Depends(get_db)):
    return finance_service.create_expense(db, payload, admin.id)


@finance_router.get("/expenses")
def list_expenses(
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    category: Optional[str] = None, q: Optional[str] = None,
    page: int = 1, page_size: int = 50,
    admin=Depends(require_admin), db: Session = Depends(get_db)
):
    items, total = finance_service.list_expenses(db, date_from, date_to, category, q, page, page_size)
    return {"items": items, "total": total}


@finance_router.get("/profit-loss")
def profit_loss(
    date_from: Optional[date] = Query(None), date_to: Optional[date] = Query(None),
    from_date: Optional[date] = Query(None, alias="from"), to_date: Optional[date] = Query(None, alias="to"),
    admin=Depends(require_admin), db: Session = Depends(get_db)
):
    f = date_from or from_date
    t = date_to or to_date
    if not t:
        t = date.today()
    if not f:
        f = t.replace(day=1)
    if f > t:
        raise HTTPException(status_code=400, detail="'from' date must be before or equal to 'to' date")
    return finance_service.get_profit_loss(db, f, t)


router.include_router(finance_router)
router.include_router(revenue_router)
router.include_router(dashboard_router)
