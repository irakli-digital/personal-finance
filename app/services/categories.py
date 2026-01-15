import os
import json
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configure Gemini
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)


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


# Category definitions
CATEGORIES: Dict[str, List[str]] = {
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


def get_all_categories() -> Dict[str, List[str]]:
    """Return the full category structure."""
    return CATEGORIES


def get_category_list() -> List[str]:
    """Return flat list of categories."""
    return list(CATEGORIES.keys())


def get_subcategories(category: str) -> List[str]:
    """Return subcategories for a given category."""
    return CATEGORIES.get(category, [])


def validate_category(category: str, subcategory: str) -> bool:
    """Validate that category and subcategory are valid."""
    if category not in CATEGORIES:
        return False
    if subcategory and subcategory not in CATEGORIES[category]:
        return False
    return True


@dataclass
class TransactionForAI:
    """Minimal transaction data for AI categorization."""
    id: int
    description: str
    partner_name: str
    transaction_type: str
    is_expense: bool
    amount: float


def build_categorization_prompt(transactions: List[TransactionForAI]) -> str:
    """Build the prompt for Gemini to categorize transactions."""

    # Build category reference
    category_ref = "\n".join([
        f"- {cat}: {', '.join(subs)}"
        for cat, subs in CATEGORIES.items()
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

    prompt = build_categorization_prompt(transactions)

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
                if category not in CATEGORIES:
                    category = "Other"
                    subcategory = "Uncategorized"
                elif subcategory not in CATEGORIES.get(category, []):
                    subcategory = CATEGORIES[category][0] if CATEGORIES[category] else "Uncategorized"

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
