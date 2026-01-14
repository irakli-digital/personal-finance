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
