from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, extract, case
from datetime import date, timedelta
from typing import Optional, Dict, List
from decimal import Decimal
from collections import defaultdict

from app.database import get_db
from app.models import Transaction
from app.schemas import TransactionListResponse, TransactionResponse, TransactionSummary
from app.services.categories import get_all_categories, validate_category, CATEGORIES, get_category_color, OVERVIEW_COLORS

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class CategoryUpdate(BaseModel):
    category: str
    subcategory: str


class BulkDeleteRequest(BaseModel):
    ids: List[int]


@router.get("/", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    start_date: Optional[date] = Query(None, description="Filter from date"),
    end_date: Optional[date] = Query(None, description="Filter to date"),
    include_internal: bool = Query(True, description="Include internal transfers"),
    source_account: Optional[str] = Query(None, description="Filter by account"),
    expenses_only: bool = Query(False, description="Show only expenses"),
    income_only: bool = Query(False, description="Show only income"),
    db: Session = Depends(get_db)
):
    """
    List transactions with pagination and filters.
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

    if expenses_only:
        query = query.filter(Transaction.is_expense == True)
    elif income_only:
        query = query.filter(Transaction.is_expense == False)

    # Get total count
    total = query.count()

    # Calculate pagination
    total_pages = (total + limit - 1) // limit
    offset = (page - 1) * limit

    # Get paginated results
    transactions = query.order_by(desc(Transaction.date), desc(Transaction.id)).offset(offset).limit(limit).all()

    return TransactionListResponse(
        transactions=[TransactionResponse.model_validate(t) for t in transactions],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )


@router.get("/summary", response_model=TransactionSummary)
async def get_summary(
    start_date: Optional[date] = Query(None, description="Filter from date"),
    end_date: Optional[date] = Query(None, description="Filter to date"),
    include_internal: bool = Query(False, description="Include internal transfers in totals"),
    source_account: Optional[str] = Query(None, description="Filter by account"),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for transactions.
    """
    # Build base query
    query = db.query(Transaction)

    # Apply filters
    if start_date:
        query = query.filter(Transaction.date >= start_date)

    if end_date:
        query = query.filter(Transaction.date <= end_date)

    if source_account:
        query = query.filter(Transaction.source_account == source_account)

    # Get total count and internal transfers count
    total_transactions = query.count()
    internal_count = query.filter(Transaction.is_internal_transfer == True).count()

    # For expense/income calculations, optionally exclude internal transfers
    calc_query = query
    if not include_internal:
        calc_query = calc_query.filter(Transaction.is_internal_transfer == False)

    # Calculate totals
    expenses_result = calc_query.filter(Transaction.is_expense == True).with_entities(
        func.coalesce(func.sum(Transaction.amount_gel), 0)
    ).scalar()

    income_result = calc_query.filter(Transaction.is_expense == False).with_entities(
        func.coalesce(func.sum(Transaction.amount_gel), 0)
    ).scalar()

    # Get date range
    date_range = query.with_entities(
        func.min(Transaction.date),
        func.max(Transaction.date)
    ).first()

    total_expenses = Decimal(str(expenses_result)) if expenses_result else Decimal("0")
    total_income = Decimal(str(income_result)) if income_result else Decimal("0")

    return TransactionSummary(
        total_transactions=total_transactions,
        total_expenses_gel=total_expenses,
        total_income_gel=total_income,
        net_gel=total_income - total_expenses,
        internal_transfers_count=internal_count,
        date_range_start=date_range[0] if date_range else None,
        date_range_end=date_range[1] if date_range else None
    )


@router.get("/accounts")
async def get_accounts(db: Session = Depends(get_db)):
    """
    Get list of unique source accounts.
    """
    accounts = db.query(Transaction.source_account).distinct().all()
    return {"accounts": [a[0] for a in accounts]}


@router.get("/categories")
async def get_categories() -> Dict[str, List[str]]:
    """
    Get all available categories and subcategories.
    """
    return get_all_categories()


@router.get("/chart-data")
async def get_chart_data(
    start_date: Optional[date] = Query(None, description="Filter from date"),
    end_date: Optional[date] = Query(None, description="Filter to date"),
    granularity: str = Query("day", description="Aggregation: day, week, month"),
    view_type: str = Query("overview", description="View: overview, expenses, income"),
    category: Optional[str] = Query(None, description="Filter by main category (for drill-down)"),
    subcategory: Optional[str] = Query(None, description="Filter by subcategory (for drill-down)"),
    include_internal: bool = Query(False, description="Include internal transfers"),
    source_account: Optional[str] = Query(None, description="Filter by account"),
    db: Session = Depends(get_db)
):
    """
    Get chart data for income/expense visualization.

    View types:
    - overview: Shows income and expense lines
    - expenses: Shows breakdown by expense categories
    - income: Shows breakdown by income categories

    When category is provided, shows subcategory breakdown.
    """
    # Build base query
    query = db.query(Transaction)

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
        if category:
            query = query.filter(Transaction.category == category)
    elif view_type == "income":
        query = query.filter(Transaction.is_expense == False)
        if category:
            query = query.filter(Transaction.category == category)

    # Get all matching transactions
    transactions = query.order_by(Transaction.date).all()

    if not transactions:
        return {"labels": [], "datasets": [], "view_type": view_type, "category": category}

    # Determine date range for labels
    if start_date and end_date:
        range_start, range_end = start_date, end_date
    elif transactions:
        range_start = transactions[0].date
        range_end = transactions[-1].date
    else:
        return {"labels": [], "datasets": [], "view_type": view_type, "category": category}

    # Generate labels based on granularity
    labels = []
    label_keys = []

    if granularity == "day":
        current = range_start
        while current <= range_end:
            labels.append(current.strftime("%d %b"))
            label_keys.append(current.isoformat())
            current += timedelta(days=1)
    elif granularity == "week":
        # Start from Monday of the first week
        current = range_start - timedelta(days=range_start.weekday())
        while current <= range_end:
            week_end = current + timedelta(days=6)
            labels.append(f"{current.strftime('%d %b')} - {week_end.strftime('%d %b')}")
            label_keys.append(current.isoformat())
            current += timedelta(weeks=1)
    elif granularity == "month":
        current = date(range_start.year, range_start.month, 1)
        while current <= range_end:
            labels.append(current.strftime("%b %Y"))
            label_keys.append(f"{current.year}-{current.month:02d}")
            # Move to next month
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

    # Helper to get the label key for a transaction date
    def get_label_key(txn_date):
        if granularity == "day":
            return txn_date.isoformat()
        elif granularity == "week":
            # Get Monday of the week
            monday = txn_date - timedelta(days=txn_date.weekday())
            return monday.isoformat()
        elif granularity == "month":
            return f"{txn_date.year}-{txn_date.month:02d}"

    datasets = []

    if view_type == "overview":
        # Two lines: Income and Expenses (fixed colors)
        income_data = defaultdict(float)
        expense_data = defaultdict(float)

        for txn in transactions:
            key = get_label_key(txn.date)
            if txn.is_expense:
                expense_data[key] += float(txn.amount_gel)
            else:
                income_data[key] += float(txn.amount_gel)

        datasets = [
            {
                "name": "Income",
                "data": [round(income_data.get(k, 0), 2) for k in label_keys],
                "color": OVERVIEW_COLORS["income"],
                "key": "income"
            },
            {
                "name": "Expenses",
                "data": [round(expense_data.get(k, 0), 2) for k in label_keys],
                "color": OVERVIEW_COLORS["expenses"],
                "key": "expenses"
            }
        ]

    elif view_type in ("expenses", "income"):
        if category:
            # Show subcategory breakdown (fixed colors)
            subcategory_data = defaultdict(lambda: defaultdict(float))

            for txn in transactions:
                key = get_label_key(txn.date)
                sub = txn.subcategory or "Uncategorized"
                subcategory_data[sub][key] += float(txn.amount_gel)

            for sub in subcategory_data.keys():
                datasets.append({
                    "name": sub,
                    "data": [round(subcategory_data[sub].get(k, 0), 2) for k in label_keys],
                    "color": get_category_color(sub),
                    "key": sub
                })
        else:
            # Show main category breakdown (fixed colors)
            category_data = defaultdict(lambda: defaultdict(float))

            for txn in transactions:
                key = get_label_key(txn.date)
                cat = txn.category or "Uncategorized"
                category_data[cat][key] += float(txn.amount_gel)

            for cat in category_data.keys():
                datasets.append({
                    "name": cat,
                    "data": [round(category_data[cat].get(k, 0), 2) for k in label_keys],
                    "color": get_category_color(cat),
                    "key": cat
                })

    # Sort datasets by total value (descending) for better visibility
    for ds in datasets:
        ds["total"] = sum(ds["data"])
    datasets.sort(key=lambda x: x["total"], reverse=True)

    # Remove the total field from output
    for ds in datasets:
        del ds["total"]

    return {
        "labels": labels,
        "datasets": datasets,
        "view_type": view_type,
        "category": category,
        "granularity": granularity
    }


# NOTE: Static routes like /all and /delete-bulk MUST come before parameterized routes like /{transaction_id}
@router.delete("/all")
async def delete_all_transactions(
    confirm: str = Query(..., description="Must be 'DELETE_ALL' to confirm"),
    db: Session = Depends(get_db)
):
    """
    Delete ALL transactions. Requires confirm='DELETE_ALL' query parameter.
    """
    if confirm != "DELETE_ALL":
        raise HTTPException(
            status_code=400,
            detail="Must provide confirm='DELETE_ALL' query parameter to delete all transactions"
        )

    deleted_count = db.query(Transaction).delete()
    db.commit()

    return {
        "message": f"Deleted all {deleted_count} transactions",
        "deleted_count": deleted_count
    }


@router.post("/delete-bulk")
async def delete_transactions_bulk(
    request: BulkDeleteRequest,
    db: Session = Depends(get_db)
):
    """
    Delete multiple transactions by IDs.
    """
    if not request.ids:
        raise HTTPException(status_code=400, detail="No transaction IDs provided")

    deleted_count = db.query(Transaction).filter(
        Transaction.id.in_(request.ids)
    ).delete(synchronize_session=False)

    db.commit()

    return {
        "message": f"Deleted {deleted_count} transactions",
        "deleted_count": deleted_count,
        "requested_count": len(request.ids)
    }


@router.patch("/{transaction_id}/category")
async def update_category(
    transaction_id: int,
    update: CategoryUpdate,
    db: Session = Depends(get_db)
):
    """
    Update the category and subcategory of a transaction.
    """
    # Validate category
    if not validate_category(update.category, update.subcategory):
        raise HTTPException(status_code=400, detail="Invalid category or subcategory")

    # Find transaction
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Update category
    transaction.category = update.category
    transaction.subcategory = update.subcategory
    transaction.ai_categorized = False  # Manual update

    db.commit()

    return {
        "id": transaction_id,
        "category": update.category,
        "subcategory": update.subcategory,
        "message": "Category updated successfully"
    }


@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a single transaction.
    """
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    db.delete(transaction)
    db.commit()

    return {
        "message": f"Transaction {transaction_id} deleted successfully",
        "deleted_id": transaction_id
    }
