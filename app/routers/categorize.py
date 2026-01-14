import logging
import asyncio
import time
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List, Tuple

from app.database import get_db
from app.models import Transaction
from app.services.categories import (
    categorize_with_gemini,
    prepare_transactions_for_ai
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/categorize", tags=["categorization"])

# Batch size for AI processing (transactions per API call)
# Keep at 50 - larger batches cause Gemini to truncate JSON responses
BATCH_SIZE = 50
# Max concurrent API calls (pay-as-you-go allows 2000 RPM)
MAX_CONCURRENT = 100


class CategorizeRequest(BaseModel):
    """Request to start categorization."""
    force_recategorize: bool = False  # If True, recategorize even already categorized


class CategorizeResponse(BaseModel):
    """Response from categorization."""
    message: str
    total_uncategorized: int
    categorized_count: int
    errors: List[str] = []


class CategorizeProgress(BaseModel):
    """Progress of categorization."""
    total: int
    processed: int
    current_batch: int
    total_batches: int


@router.get("/status")
async def get_uncategorized_count(db: Session = Depends(get_db)):
    """
    Get count of uncategorized transactions.
    """
    uncategorized = db.query(Transaction).filter(
        Transaction.category.is_(None)
    ).count()

    total = db.query(Transaction).count()

    return {
        "uncategorized": uncategorized,
        "categorized": total - uncategorized,
        "total": total
    }


async def process_batch(batch_num: int, batch: List, semaphore: asyncio.Semaphore) -> Tuple[int, List[dict], str]:
    """Process a single batch with semaphore-controlled concurrency."""
    async with semaphore:
        try:
            ai_transactions = prepare_transactions_for_ai(batch)
            results = await categorize_with_gemini(ai_transactions)
            return batch_num, results, None
        except Exception as e:
            error_msg = f"Batch {batch_num} failed: {str(e)}"
            logger.error(error_msg)
            return batch_num, [], error_msg


@router.post("/", response_model=CategorizeResponse)
async def categorize_transactions(
    request: CategorizeRequest,
    db: Session = Depends(get_db)
):
    """
    Categorize uncategorized transactions using AI.

    Processes ALL batches in PARALLEL for maximum speed.
    With pay-as-you-go, this handles hundreds of transactions in seconds.
    """
    # Get transactions to categorize
    query = db.query(Transaction)

    if not request.force_recategorize:
        # Only uncategorized transactions
        query = query.filter(Transaction.category.is_(None))

    transactions = query.order_by(Transaction.date.desc()).all()

    if not transactions:
        return CategorizeResponse(
            message="No transactions to categorize",
            total_uncategorized=0,
            categorized_count=0
        )

    total = len(transactions)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    logger.info(f"Starting parallel categorization: {total} transactions in {total_batches} batches")
    start_time = time.time()

    # Create batches
    batches = []
    for i in range(0, total, BATCH_SIZE):
        batch = transactions[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        batches.append((batch_num, batch))

    # Process all batches in parallel with semaphore to limit concurrency
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [process_batch(batch_num, batch, semaphore) for batch_num, batch in batches]
    results = await asyncio.gather(*tasks)

    # Collect all results and errors
    all_results = {}
    errors = []

    for batch_num, batch_results, error in results:
        if error:
            errors.append(error)
        else:
            for r in batch_results:
                all_results[r["id"]] = r

    # Update database with all results at once
    categorized_count = 0
    for txn in transactions:
        if txn.id in all_results:
            result = all_results[txn.id]
            txn.category = result["category"]
            txn.subcategory = result["subcategory"]
            txn.ai_categorized = True
            categorized_count += 1

    db.commit()

    elapsed = time.time() - start_time
    logger.info(f"Parallel categorization complete: {categorized_count} transactions in {elapsed:.2f}s")

    return CategorizeResponse(
        message=f"Categorization complete in {elapsed:.1f}s. Processed {categorized_count} of {total} transactions.",
        total_uncategorized=total,
        categorized_count=categorized_count,
        errors=errors
    )


@router.post("/batch")
async def categorize_batch(
    batch_size: int = BATCH_SIZE,
    db: Session = Depends(get_db)
):
    """
    Categorize a single batch of uncategorized transactions.

    Use this for incremental categorization with progress updates.
    """
    # Get uncategorized transactions
    transactions = db.query(Transaction).filter(
        Transaction.category.is_(None)
    ).order_by(Transaction.date.desc()).limit(batch_size).all()

    if not transactions:
        remaining = db.query(Transaction).filter(
            Transaction.category.is_(None)
        ).count()

        return {
            "message": "No more transactions to categorize",
            "categorized": 0,
            "remaining": remaining
        }

    try:
        # Prepare and categorize
        ai_transactions = prepare_transactions_for_ai(transactions)
        results = await categorize_with_gemini(ai_transactions)

        # Update database
        result_map = {r["id"]: r for r in results}
        categorized = 0

        for txn in transactions:
            if txn.id in result_map:
                result = result_map[txn.id]
                txn.category = result["category"]
                txn.subcategory = result["subcategory"]
                txn.ai_categorized = True
                categorized += 1

        db.commit()

        # Get remaining count
        remaining = db.query(Transaction).filter(
            Transaction.category.is_(None)
        ).count()

        return {
            "message": f"Categorized {categorized} transactions",
            "categorized": categorized,
            "remaining": remaining
        }

    except Exception as e:
        logger.error(f"Batch categorization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
