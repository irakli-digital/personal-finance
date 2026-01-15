from fastapi import FastAPI, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import date
from typing import Optional
from decimal import Decimal
import os

from app.database import engine, get_db, Base
from app.models import Transaction
from app.routers import upload, transactions, categorize
from app.services.categories import get_all_categories

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title="Personal Finance Tracker",
    description="Track and analyze personal bank transactions",
    version="1.0.0"
)

# Setup templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Include routers
app.include_router(upload.router)
app.include_router(transactions.router)
app.include_router(categorize.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_internal: bool = True,
    source_account: Optional[str] = None,
    view_type: Optional[str] = Query("overview", description="Chart view: overview, expenses, income"),
    category: Optional[str] = Query(None, description="Filter by category"),
    subcategory: Optional[str] = Query(None, description="Filter by subcategory"),
    granularity: Optional[str] = Query("day", description="Chart granularity: day, week, month"),
    db: Session = Depends(get_db)
):
    """
    Render the main dashboard with transaction table.
    """
    # Build query
    query = db.query(Transaction)

    # Apply filters
    if start_date:
        query = query.filter(Transaction.date >= start_date)

    if end_date:
        query = query.filter(Transaction.date <= end_date)

    if not include_internal:
        query = query.filter(Transaction.is_internal_transfer == False)

    if source_account:
        query = query.filter(Transaction.source_account == source_account)

    # Apply view type filters for table
    if view_type == "expenses":
        query = query.filter(Transaction.is_expense == True)
    elif view_type == "income":
        query = query.filter(Transaction.is_expense == False)

    # Apply category/subcategory filters
    if category:
        query = query.filter(Transaction.category == category)
    if subcategory:
        query = query.filter(Transaction.subcategory == subcategory)

    # Get total count
    total = query.count()

    # Calculate pagination
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    offset = (page - 1) * limit

    # Get paginated results
    transactions_list = query.order_by(
        desc(Transaction.date),
        desc(Transaction.id)
    ).offset(offset).limit(limit).all()

    # Get summary stats (excluding internal transfers)
    stats_query = db.query(Transaction)
    if start_date:
        stats_query = stats_query.filter(Transaction.date >= start_date)
    if end_date:
        stats_query = stats_query.filter(Transaction.date <= end_date)
    if source_account:
        stats_query = stats_query.filter(Transaction.source_account == source_account)

    stats_query_no_internal = stats_query.filter(Transaction.is_internal_transfer == False)

    total_expenses = stats_query_no_internal.filter(
        Transaction.is_expense == True
    ).with_entities(
        func.coalesce(func.sum(Transaction.amount_gel), 0)
    ).scalar() or Decimal("0")

    total_income = stats_query_no_internal.filter(
        Transaction.is_expense == False
    ).with_entities(
        func.coalesce(func.sum(Transaction.amount_gel), 0)
    ).scalar() or Decimal("0")

    # Get unique accounts
    accounts = db.query(Transaction.source_account).distinct().all()
    accounts = [a[0] for a in accounts]

    # Get uncategorized count
    uncategorized_count = db.query(Transaction).filter(
        Transaction.category.is_(None)
    ).count()

    # Get categories
    categories = get_all_categories()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "transactions": transactions_list,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "start_date": start_date,
            "end_date": end_date,
            "include_internal": include_internal,
            "source_account": source_account,
            "accounts": accounts,
            "total_expenses": total_expenses,
            "total_income": total_income,
            "net": total_income - total_expenses,
            "categories": categories,
            "uncategorized_count": uncategorized_count,
            "view_type": view_type,
            "selected_category": category,
            "selected_subcategory": subcategory,
            "granularity": granularity
        }
    )


@app.get("/api/table-html", response_class=HTMLResponse)
async def get_table_html(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_internal: bool = True,
    source_account: Optional[str] = None,
    view_type: Optional[str] = Query("overview", description="Chart view: overview, expenses, income"),
    category: Optional[str] = Query(None, description="Filter by category"),
    subcategory: Optional[str] = Query(None, description="Filter by subcategory"),
    db: Session = Depends(get_db)
):
    """
    Return the transactions table HTML fragment for AJAX updates.
    """
    # Build query
    query = db.query(Transaction)

    # Apply filters
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)
    if not include_internal:
        query = query.filter(Transaction.is_internal_transfer == False)
    if source_account:
        query = query.filter(Transaction.source_account == source_account)

    # Apply view type filters
    if view_type == "expenses":
        query = query.filter(Transaction.is_expense == True)
    elif view_type == "income":
        query = query.filter(Transaction.is_expense == False)

    # Apply category/subcategory filters
    if category:
        query = query.filter(Transaction.category == category)
    if subcategory:
        query = query.filter(Transaction.subcategory == subcategory)

    # Get total count
    total = query.count()

    # Calculate pagination
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    offset = (page - 1) * limit

    # Get paginated results
    transactions_list = query.order_by(
        desc(Transaction.date),
        desc(Transaction.id)
    ).offset(offset).limit(limit).all()

    # Get categories for dropdowns
    categories = get_all_categories()

    return templates.TemplateResponse(
        "partials/transactions_table.html",
        {
            "request": request,
            "transactions": transactions_list,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "categories": categories
        }
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
