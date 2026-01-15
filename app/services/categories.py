import os
import json
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import google.generativeai as genai
from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

# Configure Gemini
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# Import database components (deferred to avoid circular imports)
def _get_db_session():
    from app.database import SessionLocal
    return SessionLocal()

def _get_models():
    from app.models import Category, Subcategory
    return Category, Subcategory


# Fixed color mapping for categories (consistent across views)
CATEGORY_COLORS: Dict[str, str] = {
    # Main categories
    "Food & Dining": "#dd6b20",      # orange
    "Transportation": "#3182ce",     # blue
    "Housing": "#805ad5",            # purple
    "Shopping": "#d53f8c",           # pink
    "Entertainment": "#00b5d8",      # cyan
    "Health": "#38a169",             # green
    "Financial": "#718096",          # gray
    "Income": "#38a169",             # green (same as health, but used for income view)
    "Transfers": "#a0aec0",          # light gray
    "Other": "#4a5568",              # dark gray
    "Uncategorized": "#a0aec0",      # light gray
    # Subcategories - Food & Dining
    "Restaurants": "#ed8936",
    "Cafes & Bars": "#f6ad55",
    "Fast Food & Delivery": "#fbd38d",
    "Groceries": "#c05621",
    "Bakeries": "#dd6b20",
    # Subcategories - Transportation
    "Fuel": "#2b6cb0",
    "Parking": "#4299e1",
    "Public Transport": "#63b3ed",
    "Taxi & Rideshare": "#90cdf4",
    "Car Maintenance": "#2c5282",
    # Subcategories - Housing
    "Rent": "#6b46c1",
    "Utilities": "#9f7aea",
    "Internet & TV": "#b794f4",
    "Home Maintenance": "#553c9a",
    "Furniture": "#805ad5",
    # Subcategories - Shopping
    "Clothing": "#b83280",
    "Electronics": "#d53f8c",
    "Health & Beauty": "#ed64a6",
    "Gifts": "#f687b3",
    "Other Shopping": "#97266d",
    # Subcategories - Entertainment
    "Subscriptions": "#0987a0",
    "Movies & Events": "#00b5d8",
    "Hobbies": "#76e4f7",
    "Travel & Vacation": "#0bc5ea",
    # Subcategories - Health
    "Pharmacy": "#276749",
    "Doctor & Medical": "#38a169",
    "Gym & Fitness": "#68d391",
    "Insurance": "#48bb78",
    # Subcategories - Financial
    "Bank Fees": "#4a5568",
    "Interest Paid": "#718096",
    "Investments": "#a0aec0",
    "Currency Exchange": "#cbd5e0",
    # Subcategories - Income
    "Salary": "#2f855a",
    "Business Income": "#38a169",
    "Interest Earned": "#48bb78",
    "Refunds": "#68d391",
    "Other Income": "#9ae6b4",
    # Subcategories - Transfers
    "Internal Transfer": "#a0aec0",
    "Transfer to Others": "#cbd5e0",
    "Transfer from Others": "#e2e8f0",
    # Subcategories - Other
    "Cash Withdrawal": "#718096",
    "Miscellaneous": "#a0aec0",
}

# Special colors for overview chart
OVERVIEW_COLORS = {
    "income": "#38a169",   # green
    "expenses": "#e53e3e", # red
}


def get_category_color(name: str) -> str:
    """Get the fixed color for a category or subcategory."""
    return CATEGORY_COLORS.get(name, "#718096")  # default gray


# Default category definitions (used for seeding and fallback)
DEFAULT_CATEGORIES: Dict[str, List[str]] = {
    "Food & Dining": [
        "Restaurants",
        "Cafes & Bars",
        "Fast Food & Delivery",
        "Groceries",
        "Bakeries"
    ],
    "Transportation": [
        "Fuel",
        "Parking",
        "Public Transport",
        "Taxi & Rideshare",
        "Car Maintenance"
    ],
    "Housing": [
        "Rent",
        "Utilities",
        "Internet & TV",
        "Home Maintenance",
        "Furniture"
    ],
    "Shopping": [
        "Clothing",
        "Electronics",
        "Health & Beauty",
        "Gifts",
        "Other Shopping"
    ],
    "Entertainment": [
        "Subscriptions",
        "Movies & Events",
        "Hobbies",
        "Travel & Vacation"
    ],
    "Health": [
        "Pharmacy",
        "Doctor & Medical",
        "Gym & Fitness",
        "Insurance"
    ],
    "Financial": [
        "Bank Fees",
        "Interest Paid",
        "Investments",
        "Currency Exchange"
    ],
    "Income": [
        "Salary",
        "Business Income",
        "Interest Earned",
        "Refunds",
        "Other Income"
    ],
    "Transfers": [
        "Internal Transfer",
        "Transfer to Others",
        "Transfer from Others"
    ],
    "Other": [
        "Uncategorized",
        "Cash Withdrawal",
        "Miscellaneous"
    ]
}

# Categories that are income-related
INCOME_CATEGORIES = {"Income"}

# Backward compatibility alias
CATEGORIES = DEFAULT_CATEGORIES

# Cache for database categories
_categories_cache: Optional[Dict[str, List[str]]] = None
_cache_timestamp: float = 0
CACHE_TTL = 300  # 5 minutes


def seed_categories(db: Session = None) -> None:
    """
    Seed the database with default categories if empty.
    Call this on app startup.
    """
    Category, Subcategory = _get_models()

    close_db = False
    if db is None:
        db = _get_db_session()
        close_db = True

    try:
        # Check if categories already exist
        existing_count = db.query(Category).count()
        if existing_count > 0:
            logger.info(f"Categories already seeded ({existing_count} categories)")
            return

        logger.info("Seeding categories...")

        for order, (cat_name, subcats) in enumerate(DEFAULT_CATEGORIES.items()):
            is_income = cat_name in INCOME_CATEGORIES
            color = CATEGORY_COLORS.get(cat_name, "#718096")

            category = Category(
                name=cat_name,
                color=color,
                is_income=is_income,
                display_order=order
            )
            db.add(category)
            db.flush()  # Get the category ID

            for sub_order, sub_name in enumerate(subcats):
                sub_color = CATEGORY_COLORS.get(sub_name)
                subcategory = Subcategory(
                    name=sub_name,
                    category_id=category.id,
                    color=sub_color,
                    display_order=sub_order
                )
                db.add(subcategory)

        db.commit()
        logger.info(f"Seeded {len(DEFAULT_CATEGORIES)} categories with subcategories")

        # Clear cache
        global _categories_cache
        _categories_cache = None

    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding categories: {e}")
        raise
    finally:
        if close_db:
            db.close()


def get_all_categories(db: Session = None) -> Dict[str, List[str]]:
    """
    Return the full category structure from database.
    Falls back to defaults if database is empty.
    """
    global _categories_cache, _cache_timestamp
    import time

    # Check cache
    if _categories_cache and (time.time() - _cache_timestamp) < CACHE_TTL:
        return _categories_cache

    Category, Subcategory = _get_models()

    close_db = False
    if db is None:
        db = _get_db_session()
        close_db = True

    try:
        categories = db.query(Category).order_by(Category.display_order).all()

        if not categories:
            # Fallback to defaults if database is empty
            return DEFAULT_CATEGORIES

        result = {}
        for cat in categories:
            subcats = [s.name for s in sorted(cat.subcategories, key=lambda x: x.display_order)]
            result[cat.name] = subcats

        # Update cache
        _categories_cache = result
        _cache_timestamp = time.time()

        return result

    finally:
        if close_db:
            db.close()


def get_all_categories_with_colors(db: Session = None) -> Dict[str, Dict]:
    """
    Return categories with their colors and subcategories.
    """
    Category, Subcategory = _get_models()

    close_db = False
    if db is None:
        db = _get_db_session()
        close_db = True

    try:
        categories = db.query(Category).order_by(Category.display_order).all()

        if not categories:
            # Fallback to defaults
            return {
                name: {
                    "color": CATEGORY_COLORS.get(name, "#718096"),
                    "is_income": name in INCOME_CATEGORIES,
                    "subcategories": [
                        {"name": s, "color": CATEGORY_COLORS.get(s)}
                        for s in subs
                    ]
                }
                for name, subs in DEFAULT_CATEGORIES.items()
            }

        result = {}
        for cat in categories:
            result[cat.name] = {
                "id": cat.id,
                "color": cat.color,
                "is_income": cat.is_income,
                "subcategories": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "color": s.color or cat.color
                    }
                    for s in sorted(cat.subcategories, key=lambda x: x.display_order)
                ]
            }

        return result

    finally:
        if close_db:
            db.close()


def get_category_list(db: Session = None) -> List[str]:
    """Return flat list of categories."""
    categories = get_all_categories(db)
    return list(categories.keys())


def get_subcategories(category: str, db: Session = None) -> List[str]:
    """Return subcategories for a given category."""
    categories = get_all_categories(db)
    return categories.get(category, [])


def validate_category(category: str, subcategory: str, db: Session = None) -> bool:
    """Validate that category and subcategory are valid."""
    categories = get_all_categories(db)
    if category not in categories:
        return False
    if subcategory and subcategory not in categories[category]:
        return False
    return True


def clear_categories_cache():
    """Clear the categories cache (call after modifying categories)."""
    global _categories_cache
    _categories_cache = None


def add_category(name: str, color: str = "#718096", is_income: bool = False, db: Session = None) -> int:
    """Add a new category to the database. Returns the new category ID."""
    Category, _ = _get_models()

    close_db = False
    if db is None:
        db = _get_db_session()
        close_db = True

    try:
        # Get max display order
        max_order = db.query(Category).count()

        category = Category(
            name=name,
            color=color,
            is_income=is_income,
            display_order=max_order
        )
        db.add(category)
        db.commit()
        db.refresh(category)

        clear_categories_cache()
        return category.id

    finally:
        if close_db:
            db.close()


def add_subcategory(category_name: str, subcategory_name: str, color: str = None, db: Session = None) -> int:
    """Add a new subcategory to an existing category. Returns the new subcategory ID."""
    Category, Subcategory = _get_models()

    close_db = False
    if db is None:
        db = _get_db_session()
        close_db = True

    try:
        # Find the category
        category = db.query(Category).filter(Category.name == category_name).first()
        if not category:
            raise ValueError(f"Category '{category_name}' not found")

        # Get max display order for this category
        max_order = len(category.subcategories)

        subcategory = Subcategory(
            name=subcategory_name,
            category_id=category.id,
            color=color,
            display_order=max_order
        )
        db.add(subcategory)
        db.commit()
        db.refresh(subcategory)

        clear_categories_cache()
        return subcategory.id

    finally:
        if close_db:
            db.close()


@dataclass
class TransactionForAI:
    """Minimal transaction data for AI categorization."""
    id: int
    description: str
    partner_name: str
    transaction_type: str
    is_expense: bool
    amount: float


def build_categorization_prompt(transactions: List[TransactionForAI], categories: Dict[str, List[str]] = None) -> str:
    """Build the prompt for Gemini to categorize transactions."""

    # Use provided categories or get from database
    if categories is None:
        categories = get_all_categories()

    # Build category reference
    category_ref = "\n".join([
        f"- {cat}: {', '.join(subs)}"
        for cat, subs in categories.items()
    ])

    # Build transaction list
    txn_list = "\n".join([
        f"{i+1}. ID:{t.id} | {t.description[:100] if t.description else 'N/A'} | "
        f"Partner: {t.partner_name[:50] if t.partner_name else 'N/A'} | "
        f"Type: {t.transaction_type or 'N/A'} | "
        f"{'Expense' if t.is_expense else 'Income'}: {t.amount:.2f} GEL"
        for i, t in enumerate(transactions)
    ])

    prompt = f"""You are a financial transaction categorizer. Categorize each transaction into the appropriate category and subcategory.

AVAILABLE CATEGORIES AND SUBCATEGORIES:
{category_ref}

TRANSACTIONS TO CATEGORIZE:
{txn_list}

RULES:
1. For transfers between own accounts, use "Transfers" > "Internal Transfer"
2. For salary/income payments, use "Income" > appropriate subcategory
3. For Wolt, Glovo, Bolt Food use "Food & Dining" > "Fast Food & Delivery"
4. For Bolt, Yandex taxi use "Transportation" > "Taxi & Rideshare"
5. For currency exchange/conversion use "Financial" > "Currency Exchange"
6. For interest earned use "Income" > "Interest Earned"
7. For SPAR, Carrefour, Goodwill use "Food & Dining" > "Groceries"
8. For restaurants, cafes use "Food & Dining" > "Restaurants" or "Cafes & Bars"
9. For parking use "Transportation" > "Parking"
10. For Silknet, Magti, Geocell use "Housing" > "Internet & TV"

Return ONLY a valid JSON array with this exact format (no markdown, no explanation):
[{{"id": <transaction_id>, "category": "<category>", "subcategory": "<subcategory>"}}]

Respond with the JSON array only:"""

    return prompt


async def categorize_with_gemini(transactions: List[TransactionForAI]) -> List[Dict]:
    """
    Use Gemini to categorize a batch of transactions.

    Returns list of dicts with id, category, subcategory.
    """
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY not configured")

    if not transactions:
        return []

    # Get categories from database
    categories = get_all_categories()

    prompt = build_categorization_prompt(transactions, categories)

    try:
        model = genai.GenerativeModel('gemini-2.0-flash')

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,  # Low temperature for consistency
                max_output_tokens=8192,  # Increased for larger batches
            )
        )

        # Extract text response
        response_text = response.text.strip()

        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        # Parse JSON
        results = json.loads(response_text)

        # Validate and filter results
        validated_results = []
        for result in results:
            if isinstance(result, dict) and "id" in result:
                category = result.get("category", "Other")
                subcategory = result.get("subcategory", "Uncategorized")

                # Validate category exists
                if category not in categories:
                    category = "Other"
                    subcategory = "Uncategorized"
                elif subcategory not in categories.get(category, []):
                    subcategory = categories[category][0] if categories[category] else "Uncategorized"

                validated_results.append({
                    "id": result["id"],
                    "category": category,
                    "subcategory": subcategory
                })

        return validated_results

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        logger.error(f"Response was: {response_text[:500]}")
        raise ValueError(f"Invalid JSON response from AI: {e}")
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        raise


def prepare_transactions_for_ai(transactions) -> List[TransactionForAI]:
    """Convert database transactions (SQLAlchemy models) to AI-ready format."""
    result = []
    for t in transactions:
        # Handle SQLAlchemy model objects
        result.append(TransactionForAI(
            id=t.id,
            description=t.description or "",
            partner_name=t.partner_name or "",
            transaction_type=t.transaction_type or "",
            is_expense=t.is_expense,
            amount=float(t.amount_gel) if t.amount_gel else 0.0
        ))
    return result
