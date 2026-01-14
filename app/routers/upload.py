from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import UploadResponse
from app.services.csv_parser import (
    parse_csv_content,
    get_existing_transaction_ids,
    filter_duplicates,
    save_transactions,
    detect_internal_transfers
)

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a CSV file containing bank transactions.

    The file should be a TBC Bank account statement CSV export.
    The account number will be extracted from the filename.
    Duplicate transactions (same transaction_id + source_account) will be skipped.
    """
    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV file")

    # Read file content
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")

    # Check file size (max 10MB)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10MB.")

    # Parse CSV
    try:
        transactions, source_account = parse_csv_content(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing CSV: {str(e)}")

    if not transactions:
        raise HTTPException(status_code=400, detail="No valid transactions found in CSV")

    total_in_file = len(transactions)

    # Get existing transaction IDs for this account
    existing_ids = get_existing_transaction_ids(db, source_account)

    # Filter duplicates
    new_transactions, duplicates_count = filter_duplicates(transactions, existing_ids)

    # Save new transactions
    saved_count = save_transactions(db, new_transactions)

    # Detect and mark internal transfers
    if saved_count > 0:
        detect_internal_transfers(db)

    return UploadResponse(
        message=f"Successfully processed {file.filename}",
        new_transactions=saved_count,
        duplicates_skipped=duplicates_count,
        total_in_file=total_in_file,
        source_account=source_account
    )
