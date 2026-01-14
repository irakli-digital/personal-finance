from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List


class TransactionBase(BaseModel):
    """Base schema for transaction data."""
    transaction_id: str
    source_account: str
    date: date
    description: Optional[str] = None
    additional_info: Optional[str] = None
    amount_gel: Decimal
    amount_usd: Optional[Decimal] = None
    is_expense: bool
    is_internal_transfer: bool = False
    balance_gel: Optional[Decimal] = None
    transaction_type: Optional[str] = None
    partner_name: Optional[str] = None
    partner_account: Optional[str] = None
    document_number: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    ai_categorized: bool = False


class TransactionCreate(TransactionBase):
    """Schema for creating a transaction."""
    pass


class TransactionResponse(TransactionBase):
    """Schema for transaction response."""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class TransactionListResponse(BaseModel):
    """Schema for paginated transaction list."""
    transactions: List[TransactionResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class UploadResponse(BaseModel):
    """Schema for upload response."""
    message: str
    new_transactions: int
    duplicates_skipped: int
    total_in_file: int
    source_account: str


class TransactionSummary(BaseModel):
    """Schema for transaction summary statistics."""
    total_transactions: int
    total_expenses_gel: Decimal
    total_income_gel: Decimal
    net_gel: Decimal
    internal_transfers_count: int
    date_range_start: Optional[date] = None
    date_range_end: Optional[date] = None


class ErrorResponse(BaseModel):
    """Schema for error responses."""
    detail: str
