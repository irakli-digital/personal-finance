from sqlalchemy import Column, Integer, String, Date, Numeric, Boolean, DateTime, UniqueConstraint, Index, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Category(Base):
    """Category model for organizing transactions."""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    color = Column(String(20), default="#718096")  # Hex color for UI
    icon = Column(String(50), nullable=True)  # Optional icon name
    is_income = Column(Boolean, default=False)  # True for income categories
    display_order = Column(Integer, default=0)  # For custom ordering
    created_at = Column(DateTime, server_default=func.now())

    # Relationship to subcategories
    subcategories = relationship("Subcategory", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Category(id={self.id}, name={self.name})>"


class Subcategory(Base):
    """Subcategory model for detailed transaction classification."""

    __tablename__ = "subcategories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    color = Column(String(20), nullable=True)  # Optional, inherits from category if null
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    # Relationship to parent category
    category = relationship("Category", back_populates="subcategories")

    __table_args__ = (
        UniqueConstraint('name', 'category_id', name='uix_subcategory_name_category'),
    )

    def __repr__(self):
        return f"<Subcategory(id={self.id}, name={self.name}, category_id={self.category_id})>"


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
