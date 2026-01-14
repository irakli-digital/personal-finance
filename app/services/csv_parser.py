import csv
import re
import io
import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Tuple, Optional, Set
from sqlalchemy.orm import Session

from app.models import Transaction
from app.schemas import TransactionCreate


# Column indices (0-based) based on TBC Bank CSV format
class CSVColumns:
    DATE = 0
    DESCRIPTION = 1
    ADDITIONAL_INFO = 2
    PAID_OUT = 3
    PAID_OUT_EQUIV = 4
    PAID_IN = 5
    PAID_IN_EQUIV = 6
    BALANCE = 7
    BALANCE_EQUIV = 8
    TYPE = 9
    DOCUMENT_DATE = 10
    DOCUMENT_NUMBER = 11
    PARTNER_ACCOUNT = 12
    PARTNER_NAME = 13
    TRANSACTION_ID = 25  # Last column


def extract_account_number(filename: str) -> str:
    """
    Extract account number from filename.
    Expected format: account_statement_14274656_14102025_14012026_equ.csv
    """
    match = re.search(r'account_statement_(\d+)_', filename)
    if match:
        return match.group(1)

    # Fallback: try to find any 8-digit number in filename
    match = re.search(r'(\d{8})', filename)
    if match:
        return match.group(1)

    # Default if no account number found
    return "unknown"


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date from DD/MM/YYYY format."""
    if not date_str or not date_str.strip():
        return None

    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_decimal(value: str) -> Optional[Decimal]:
    """Parse decimal value, handling empty strings and formatting."""
    if not value or not value.strip():
        return None

    try:
        # Remove any whitespace and convert
        clean_value = value.strip().replace(',', '.')
        return Decimal(clean_value)
    except InvalidOperation:
        return None


def detect_currency_type(paid_out: Optional[Decimal], paid_out_equiv: Optional[Decimal],
                         paid_in: Optional[Decimal], paid_in_equiv: Optional[Decimal]) -> str:
    """
    Detect if transaction is from GEL or USD account.
    GEL account: paid_out == paid_out_equiv (same currency)
    USD account: paid_out != paid_out_equiv (different currencies)
    """
    if paid_out and paid_out_equiv:
        if abs(paid_out - paid_out_equiv) < Decimal("0.01"):
            return "GEL"
        return "USD"

    if paid_in and paid_in_equiv:
        if abs(paid_in - paid_in_equiv) < Decimal("0.01"):
            return "GEL"
        return "USD"

    return "GEL"  # Default to GEL


def parse_csv_content(content: bytes, filename: str) -> Tuple[List[TransactionCreate], str]:
    """
    Parse CSV content and return list of transactions.

    Returns:
        Tuple of (list of TransactionCreate objects, source_account)
    """
    # Decode content (handle BOM)
    try:
        text_content = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text_content = content.decode('utf-8', errors='ignore')

    # Extract account number from filename
    source_account = extract_account_number(filename)

    # Parse CSV
    reader = csv.reader(io.StringIO(text_content))
    rows = list(reader)

    if len(rows) < 3:
        raise ValueError("CSV file too short. Expected at least 3 rows (headers + data).")

    # Skip first two header rows (Georgian + English)
    data_rows = rows[2:]

    transactions = []

    for row_num, row in enumerate(data_rows, start=3):
        # Skip empty rows
        if not row or not any(cell.strip() for cell in row):
            continue

        # Ensure row has enough columns
        if len(row) < 26:
            continue

        # Extract values
        date_val = parse_date(row[CSVColumns.DATE])
        if not date_val:
            continue  # Skip rows without valid date

        description = row[CSVColumns.DESCRIPTION].strip() if row[CSVColumns.DESCRIPTION] else None
        additional_info = row[CSVColumns.ADDITIONAL_INFO].strip() if row[CSVColumns.ADDITIONAL_INFO] else None

        paid_out = parse_decimal(row[CSVColumns.PAID_OUT])
        paid_out_equiv = parse_decimal(row[CSVColumns.PAID_OUT_EQUIV])
        paid_in = parse_decimal(row[CSVColumns.PAID_IN])
        paid_in_equiv = parse_decimal(row[CSVColumns.PAID_IN_EQUIV])
        balance_equiv = parse_decimal(row[CSVColumns.BALANCE_EQUIV])

        transaction_type = row[CSVColumns.TYPE].strip() if row[CSVColumns.TYPE] else None
        document_number = row[CSVColumns.DOCUMENT_NUMBER].strip() if row[CSVColumns.DOCUMENT_NUMBER] else None
        partner_account = row[CSVColumns.PARTNER_ACCOUNT].strip() if row[CSVColumns.PARTNER_ACCOUNT] else None
        partner_name = row[CSVColumns.PARTNER_NAME].strip() if row[CSVColumns.PARTNER_NAME] else None
        transaction_id = row[CSVColumns.TRANSACTION_ID].strip() if row[CSVColumns.TRANSACTION_ID] else None

        # Generate deterministic ID for transactions without one
        if not transaction_id:
            # Use multiple fields for robust deduplication
            # Normalize strings to ensure consistency
            fallback_parts = [
                str(date_val),
                (description or "").strip().lower(),
                (additional_info or "").strip().lower(),
                str(paid_out_equiv or paid_in_equiv or "0"),
                source_account,
                (document_number or "").strip(),
                (partner_account or "").strip()
            ]
            # Use SHA256 for deterministic hashing across sessions
            hash_input = '|'.join(fallback_parts).encode('utf-8')
            hash_digest = hashlib.sha256(hash_input).hexdigest()[:16]
            transaction_id = f"gen_{hash_digest}"

        # Determine if expense or income
        is_expense = paid_out is not None and paid_out > 0

        # Calculate GEL amount (use equiv columns)
        if is_expense:
            amount_gel = paid_out_equiv or paid_out or Decimal("0")
        else:
            amount_gel = paid_in_equiv or paid_in or Decimal("0")

        # Determine USD amount (only if different from GEL)
        currency_type = detect_currency_type(paid_out, paid_out_equiv, paid_in, paid_in_equiv)
        amount_usd = None
        if currency_type == "USD":
            amount_usd = paid_out if is_expense else paid_in

        # Create transaction object
        transaction = TransactionCreate(
            transaction_id=transaction_id,
            source_account=source_account,
            date=date_val,
            description=description,
            additional_info=additional_info,
            amount_gel=amount_gel,
            amount_usd=amount_usd,
            is_expense=is_expense,
            is_internal_transfer=False,  # Will be updated later
            balance_gel=balance_equiv,
            transaction_type=transaction_type,
            partner_name=partner_name,
            partner_account=partner_account,
            document_number=document_number
        )

        transactions.append(transaction)

    return transactions, source_account


def get_existing_transaction_ids(db: Session, source_account: str) -> Set[str]:
    """Get set of existing transaction IDs for a source account."""
    results = db.query(Transaction.transaction_id).filter(
        Transaction.source_account == source_account
    ).all()

    return {r[0] for r in results}


def filter_duplicates(
    transactions: List[TransactionCreate],
    existing_ids: Set[str]
) -> Tuple[List[TransactionCreate], int]:
    """
    Filter out duplicate transactions.

    Returns:
        Tuple of (new_transactions, duplicates_count)
    """
    new_transactions = []
    duplicates = 0

    for txn in transactions:
        if txn.transaction_id in existing_ids:
            duplicates += 1
        else:
            new_transactions.append(txn)
            existing_ids.add(txn.transaction_id)  # Prevent duplicates within same file

    return new_transactions, duplicates


def detect_internal_transfers(db: Session) -> int:
    """
    Detect and mark internal transfers in the database.
    An internal transfer is identified when the same transaction_id
    exists across different source accounts.

    Returns:
        Number of transactions marked as internal transfers
    """
    from sqlalchemy import func

    # Find transaction_ids that appear in multiple source accounts
    subquery = db.query(
        Transaction.transaction_id
    ).group_by(
        Transaction.transaction_id
    ).having(
        func.count(func.distinct(Transaction.source_account)) > 1
    ).subquery()

    # Update those transactions to mark as internal transfers
    updated = db.query(Transaction).filter(
        Transaction.transaction_id.in_(subquery)
    ).update(
        {Transaction.is_internal_transfer: True},
        synchronize_session=False
    )

    db.commit()

    return updated


def save_transactions(db: Session, transactions: List[TransactionCreate]) -> int:
    """
    Save transactions to database.

    Returns:
        Number of transactions saved
    """
    if not transactions:
        return 0

    db_transactions = [
        Transaction(
            transaction_id=txn.transaction_id,
            source_account=txn.source_account,
            date=txn.date,
            description=txn.description,
            additional_info=txn.additional_info,
            amount_gel=txn.amount_gel,
            amount_usd=txn.amount_usd,
            is_expense=txn.is_expense,
            is_internal_transfer=txn.is_internal_transfer,
            balance_gel=txn.balance_gel,
            transaction_type=txn.transaction_type,
            partner_name=txn.partner_name,
            partner_account=txn.partner_account,
            document_number=txn.document_number
        )
        for txn in transactions
    ]

    db.bulk_save_objects(db_transactions)
    db.commit()

    return len(db_transactions)
