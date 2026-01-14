from sqlalchemy import Column, Integer, String, Date, Numeric, Boolean, DateTime, UniqueConstraint, Index
from sqlalchemy.sql import func
from app.database import Base


class Transaction(Base):
    """Transaction model representing a bank transaction."""

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String(50), nullable=False)
    source_account = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    description = Column(String(500))
    additional_info = Column(String(1000))
    amount_gel = Column(Numeric(15, 2), nullable=False)
    amount_usd = Column(Numeric(15, 2), nullable=True)
    is_expense = Column(Boolean, nullable=False)
    is_internal_transfer = Column(Boolean, default=False)
    balance_gel = Column(Numeric(15, 2))
    transaction_type = Column(String(100))
    partner_name = Column(String(255))
    partner_account = Column(String(100))
    document_number = Column(String(50))
    category = Column(String(50), nullable=True)
    subcategory = Column(String(50), nullable=True)
    ai_categorized = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    # Composite unique constraint for deduplication
    __table_args__ = (
        UniqueConstraint('transaction_id', 'source_account', name='uix_transaction_source'),
        Index('idx_transactions_date', 'date'),
        Index('idx_transactions_source', 'source_account'),
        Index('idx_transactions_internal', 'is_internal_transfer'),
        Index('idx_transactions_category', 'category'),
    )

    def __repr__(self):
        return f"<Transaction(id={self.id}, date={self.date}, amount_gel={self.amount_gel})>"
