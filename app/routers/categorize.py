import logging
import asyncio
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List, Tuple, Dict
from threading import Thread
from enum import Enum

from app.database import get_db, SessionLocal
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


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskState:
    """State for a background categorization task."""
    def __init__(self, total: int):
        self.status: TaskStatus = TaskStatus.PENDING
        self.total: int = total
        self.processed: int = 0
        self.categorized: int = 0
        self.errors: List[str] = []
        self.cancel_requested: bool = False
        self.started_at: float = None
        self.completed_at: float = None


# In-memory task storage (single task at a time for simplicity)
_current_task: Dict[str, TaskState] = {}


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


class TaskResponse(BaseModel):
    """Response for task operations."""
    task_id: str
    status: str
    total: int
    processed: int
    categorized: int
    errors: List[str] = []
    elapsed_seconds: Optional[float] = None


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


def run_categorization_sync(task_id: str, transaction_ids: List[int]):
    """
    Run categorization in a background thread.
    This runs synchronously in its own thread with its own DB session.
    """
    task = _current_task.get(task_id)
    if not task:
        return

    task.status = TaskStatus.RUNNING
    task.started_at = time.time()

    # Create a new DB session for this thread
    db = SessionLocal()

    try:
        # Process in batches
        total_batches = (len(transaction_ids) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num in range(total_batches):
            # Check for cancellation
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                logger.info(f"Task {task_id} cancelled after {task.processed} transactions")
                break

            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(transaction_ids))
            batch_ids = transaction_ids[start_idx:end_idx]

            # Get transactions for this batch
            transactions = db.query(Transaction).filter(
                Transaction.id.in_(batch_ids)
            ).all()

            if not transactions:
                continue

            try:
                # Prepare and categorize
                ai_transactions = prepare_transactions_for_ai(transactions)

                # Run async categorization in a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(categorize_with_gemini(ai_transactions))
                finally:
                    loop.close()

                # Update database
                result_map = {r["id"]: r for r in results}

                for txn in transactions:
                    if txn.id in result_map:
                        result = result_map[txn.id]
                        txn.category = result["category"]
                        txn.subcategory = result["subcategory"]
                        txn.ai_categorized = True
                        task.categorized += 1

                db.commit()
                task.processed += len(transactions)

            except Exception as e:
                error_msg = f"Batch {batch_num + 1} failed: {str(e)}"
                logger.error(error_msg)
                task.errors.append(error_msg)
                task.processed += len(transactions)

        # Mark complete if not cancelled
        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.COMPLETED

        task.completed_at = time.time()
        logger.info(f"Task {task_id} completed: {task.categorized}/{task.total} categorized")

    except Exception as e:
        task.status = TaskStatus.FAILED
        task.errors.append(str(e))
        logger.error(f"Task {task_id} failed: {e}")
    finally:
        db.close()


@router.post("/start")
async def start_categorization(db: Session = Depends(get_db)):
    """
    Start background categorization task.
    Returns immediately with a task_id for polling.
    """
    global _current_task

    # Check if there's already a running task
    for tid, task in _current_task.items():
        if task.status == TaskStatus.RUNNING:
            return {
                "task_id": tid,
                "status": task.status.value,
                "message": "A categorization task is already running",
                "total": task.total,
                "processed": task.processed,
                "categorized": task.categorized
            }

    # Get uncategorized transactions
    transactions = db.query(Transaction).filter(
        Transaction.category.is_(None)
    ).order_by(Transaction.date.desc()).all()

    if not transactions:
        return {
            "task_id": None,
            "status": "completed",
            "message": "No transactions to categorize",
            "total": 0,
            "processed": 0,
            "categorized": 0
        }

    # Create new task
    task_id = str(uuid.uuid4())[:8]
    transaction_ids = [t.id for t in transactions]

    _current_task[task_id] = TaskState(total=len(transaction_ids))

    # Start background thread
    thread = Thread(
        target=run_categorization_sync,
        args=(task_id, transaction_ids),
        daemon=True
    )
    thread.start()

    logger.info(f"Started categorization task {task_id} with {len(transaction_ids)} transactions")

    return {
        "task_id": task_id,
        "status": "pending",
        "message": f"Started categorizing {len(transaction_ids)} transactions",
        "total": len(transaction_ids),
        "processed": 0,
        "categorized": 0
    }


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """
    Get status of a categorization task.
    """
    task = _current_task.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    elapsed = None
    if task.started_at:
        end_time = task.completed_at or time.time()
        elapsed = round(end_time - task.started_at, 1)

    return {
        "task_id": task_id,
        "status": task.status.value,
        "total": task.total,
        "processed": task.processed,
        "categorized": task.categorized,
        "errors": task.errors,
        "elapsed_seconds": elapsed
    }


@router.post("/task/{task_id}/cancel")
async def cancel_task(task_id: str):
    """
    Cancel a running categorization task.
    """
    task = _current_task.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.RUNNING:
        return {
            "task_id": task_id,
            "status": task.status.value,
            "message": f"Task is not running (status: {task.status.value})"
        }

    task.cancel_requested = True

    return {
        "task_id": task_id,
        "status": "cancelling",
        "message": "Cancel requested, task will stop after current batch"
    }


@router.get("/active")
async def get_active_task():
    """
    Get the currently active task, if any.
    """
    for tid, task in _current_task.items():
        if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
            elapsed = None
            if task.started_at:
                elapsed = round(time.time() - task.started_at, 1)

            return {
                "task_id": tid,
                "status": task.status.value,
                "total": task.total,
                "processed": task.processed,
                "categorized": task.categorized,
                "elapsed_seconds": elapsed
            }

    return {
        "task_id": None,
        "status": "none",
        "message": "No active categorization task"
    }


# Keep the old batch endpoint for compatibility
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
