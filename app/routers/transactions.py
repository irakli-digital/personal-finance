from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import date
from typing import Optional, Dict, List
from decimal import Decimal

from app.database import get_db
from app.models import Transaction
from app.schemas import TransactionListResponse, TransactionResponse, TransactionSummary
from app.services.categories import get_all_categories, validate_category

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
