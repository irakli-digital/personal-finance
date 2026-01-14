# Personal Finance Tracker - Product Requirements Document

## Overview

A personal finance web application that allows users to upload bank account CSV statements, store transactions in a database, and view spending data in a simple dashboard. The primary use case is tracking expenses from TBC Bank (Georgia) account statements in both GEL (Georgian Lari) and USD currencies.

## Problem Statement

Managing personal finances across multiple bank accounts (GEL and USD) requires:
1. Consolidating transaction data from multiple CSV exports
2. Avoiding duplicate transactions when uploading overlapping date ranges
3. Converting and normalizing amounts to a single currency (GEL) for analysis
4. Identifying internal transfers between own accounts to avoid skewing expense reports

## Goals

### MVP Goals
- Upload CSV files from TBC Bank account statements
- Parse and store transactions in PostgreSQL database
- Deduplicate transactions automatically when uploading overlapping periods
- Display all transactions in a simple, sortable table
- Track both GEL and USD amounts where applicable

### Future Goals (Post-MVP)
- Category-based expense breakdown
- Monthly spending summaries and trends
- Data visualization (charts/graphs)
- Budget tracking and alerts
- Multi-user support

## Technical Architecture

### Tech Stack
| Component | Technology |
|-----------|------------|
| Backend | Python FastAPI |
| Database | PostgreSQL (Neon) |
| ORM | SQLAlchemy |
| Frontend | Jinja2 Templates + HTML/CSS/JS |
| Deployment | TBD |

### Project Structure
```
Personal Finance/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── database.py          # Database connection and session management
│   ├── models.py            # SQLAlchemy ORM models
│   ├── schemas.py           # Pydantic validation schemas
│   ├── routers/
│   │   ├── upload.py        # CSV upload endpoint
│   │   └── transactions.py  # Transaction CRUD endpoints
│   ├── services/
│   │   └── csv_parser.py    # CSV parsing and deduplication logic
│   └── templates/
│       └── dashboard.html   # Main dashboard view
├── Raw CSV/                  # Sample CSV files (not committed)
├── .env                      # Environment variables (DATABASE_URL)
├── requirements.txt          # Python dependencies
└── PRD.md                    # This document
```

## Data Model

### CSV Source Format (TBC Bank)

The bank exports CSV files with 26 columns in bilingual format (Georgian + English headers):

| Column | English Name | Description |
|--------|--------------|-------------|
| 1 | Date | Transaction date (DD/MM/YYYY) |
| 2 | Description | Transaction description |
| 3 | Additional Information | Extended details |
| 4 | Paid Out | Amount debited (original currency) |
| 5 | Paid Out Equiv. | Amount debited (GEL equivalent) |
| 6 | Paid In | Amount credited (original currency) |
| 7 | Paid In Equiv. | Amount credited (GEL equivalent) |
| 8 | Balance | Account balance (original currency) |
| 9 | Balance Equiv. | Account balance (GEL equivalent) |
| 10 | Type | Transaction type |
| 11 | Document Date | Document processing date |
| 12 | Document Number | Bank document reference |
| 13 | Partner's Account | Counterparty account number |
| 14 | Partner's Name | Counterparty name |
| 15 | Partner's Tax Code | Counterparty tax ID |
| 16 | Partner's Bank Code | Counterparty bank SWIFT/BIC |
| 17 | Partner's Bank | Counterparty bank name |
| 18 | Intermediary Bank Code | Intermediary SWIFT (if applicable) |
| 19 | Intermediary Bank | Intermediary bank name |
| 20 | Charge Details | Fee/charge type |
| 21 | Taxpayer Code | User's tax code |
| 22 | Taxpayer Name | User's name |
| 23 | Treasury Code | Treasury reference |
| 24 | Op. Code | Operation code |
| 25 | Additional Description | Extra notes |
| 26 | Transaction ID | **Unique transaction identifier** |

### Database Schema

```sql
CREATE TABLE transactions (
    id SERIAL PRIMARY KEY,
    transaction_id VARCHAR(50) NOT NULL,
    source_account VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    description TEXT,
    additional_info TEXT,
    amount_gel DECIMAL(15, 2) NOT NULL,
    amount_usd DECIMAL(15, 2),
    is_expense BOOLEAN NOT NULL,
    is_internal_transfer BOOLEAN DEFAULT FALSE,
    balance_gel DECIMAL(15, 2),
    transaction_type VARCHAR(100),
    partner_name VARCHAR(255),
    partner_account VARCHAR(100),
    document_number VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(transaction_id, source_account)
);

CREATE INDEX idx_transactions_date ON transactions(date);
CREATE INDEX idx_transactions_source ON transactions(source_account);
CREATE INDEX idx_transactions_internal ON transactions(is_internal_transfer);
```

## Core Features

### 1. CSV Upload

**Endpoint**: `POST /upload`

**Functionality**:
- Accept CSV file upload
- Extract account number from filename (e.g., `account_statement_14274656_...csv` → `14274656`)
- Parse CSV with proper encoding (UTF-8 with BOM)
- Skip header rows (Georgian + English)
- Validate and transform data

**Account Detection**:
- GEL Account: `Paid Out` equals `Paid Out Equiv.` (same currency)
- USD Account: `Paid Out` differs from `Paid Out Equiv.` (converted to GEL)

### 2. Deduplication Strategy

**Problem**: User may upload 3-month statements, then upload again a week later with overlapping dates.

**Solution**: Composite unique key

```
Unique Key = (transaction_id, source_account)
```

**Why both fields?**
- Same `transaction_id` can appear in multiple account statements
- Example: Currency exchange between USD→GEL accounts uses the same Transaction ID on both sides
- Each side is a valid, separate record (one debit, one credit)

**Implementation**:
1. Parse uploaded CSV
2. Extract all `transaction_id` values
3. Query DB for existing `(transaction_id, source_account)` pairs
4. Filter out duplicates
5. Bulk insert only new transactions

### 3. Internal Transfer Detection

**Problem**: Transfers between user's own accounts are not actual expenses/income.

**Detection Methods**:
1. **Same Transaction ID across accounts**: When the same `transaction_id` exists in multiple `source_account` records
2. **Partner Account Match**: When `partner_account` matches another account owned by user

**Flag**: `is_internal_transfer = TRUE`

**Dashboard Impact**: Option to show/hide internal transfers for accurate expense analysis.

### 4. Dashboard (MVP)

**URL**: `GET /`

**Features**:
- Sortable table with columns:
  - Date
  - Description
  - Amount (GEL)
  - Amount (USD) - if applicable
  - Type
  - Partner Name
- Toggle: Show/Hide internal transfers
- Filter: Date range selector
- Pagination: 50 transactions per page

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard view (HTML) |
| POST | `/upload` | Upload CSV file |
| GET | `/api/transactions` | List transactions (JSON) |
| GET | `/api/transactions/summary` | Basic statistics |

### Query Parameters for `/api/transactions`

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | int | Page number (default: 1) |
| `limit` | int | Items per page (default: 50) |
| `start_date` | date | Filter from date |
| `end_date` | date | Filter to date |
| `include_internal` | bool | Include internal transfers (default: true) |
| `source_account` | string | Filter by account |

## User Flow

```
┌─────────────────────────────────────────────────────────┐
│                    User Journey                          │
└─────────────────────────────────────────────────────────┘

1. User exports CSV from TBC Bank online banking
   └── Downloads: account_statement_14274656_...csv

2. User visits dashboard (/)
   └── Sees existing transactions (or empty state)

3. User clicks "Upload CSV"
   └── Selects one or more CSV files

4. System processes upload:
   ├── Extracts account number from filename
   ├── Parses transactions
   ├── Deduplicates against existing records
   ├── Inserts new transactions
   └── Returns: "Added X new transactions, Y duplicates skipped"

5. Dashboard refreshes with updated data
   └── User can sort, filter, and analyze spending
```

## Error Handling

| Error | Response |
|-------|----------|
| Invalid CSV format | 400: "Invalid CSV format. Expected TBC Bank statement." |
| Missing Transaction ID | 400: "Row X missing Transaction ID" |
| Database connection failed | 500: "Database unavailable" |
| File too large (>10MB) | 413: "File too large" |

## Security Considerations

- No authentication in MVP (single-user local use)
- Database credentials in `.env` (not committed to git)
- Input validation on all CSV data
- SQL injection prevention via SQLAlchemy ORM

## Success Metrics

| Metric | Target |
|--------|--------|
| Upload speed | < 5 seconds for 500 transactions |
| Deduplication accuracy | 100% (no duplicate records) |
| Page load time | < 2 seconds |

## Future Enhancements

1. **Categories**: Auto-categorize transactions by MCC code or merchant name
2. **Charts**: Monthly spending trends, category pie charts
3. **Export**: Download filtered data as CSV/Excel
4. **Multi-currency**: Support EUR and other currencies
5. **Recurring detection**: Identify subscriptions and recurring payments
6. **Budget alerts**: Set spending limits and get notifications
7. **Authentication**: Multi-user support with login

## Appendix

### Sample Transaction IDs

| Scenario | Account A (USD) | Account B (GEL) |
|----------|-----------------|-----------------|
| Currency Exchange | `18171921369` (OUT) | `18171921369` (IN) |
| POS Purchase | - | `17441372218` |
| Interest Payment | `17625581916` | - |

### Account Numbers (from filenames)

- `14274656`: USD Account
- `14274662`: GEL Account

---

*Document Version: 1.0*
*Last Updated: January 2026*
