"""
Item-level edge case cleaning rules.

Ported from V1 _clean_single_row() and clean_receipt_data().

Handles:
- SCHARRELEI eggs (6-pack vs 20-pack detection by price)
- Mathematical bundles ("10+2", "12X330")
- Pack identifiers ("6BL", "12P", "8ST", "12ROL")
- Trailing prices & OCR artifacts
"""

import re
from typing import Dict, List, Optional, Tuple

from v2.common.non_products import is_non_product_item


# Items that should NOT have pack/bundle cleaning applied
# (they contain numbers but are product names, not quantities)
EXCLUDED_FROM_CLEANING = {
    "DUVEL 666", "4 FORMAG", "ML", "MACH3", "HEMA", "GR", "CL", "48+"
}


def apply_edge_cases(
    item_name: str,
    line_total_paid_amount: float,
    measurement_quantity: Optional[float] = None,
    measurement_type: str = "discrete_units"
) -> Tuple[str, Optional[float], Optional[float], List[str]]:
    """
    Apply edge case cleaning rules to a single item.

    Ported from V1 _clean_single_row().

    Args:
        item_name: Raw item name (should already be uppercased)
        line_total_paid_amount: Total amount paid for this item
        measurement_quantity: Current quantity (may be modified)
        measurement_type: "discrete_units" or "weight_in_grams"

    Returns:
        Tuple of (cleaned_name, new_quantity, new_price_per_unit, applied_rules)
    """
    applied_rules = []
    raw_name = str(item_name).upper().strip()
    paid_amount = float(line_total_paid_amount) if line_total_paid_amount else 0.0
    qty = float(measurement_quantity) if measurement_quantity is not None else None

    # ============================================================
    # Edge Case 1 & 2: Scharrelei (Eggs)
    # ============================================================
    if 'SCHARREL' in raw_name:
        applied_rules.append("clean_scharrelei")
        qty_match = re.search(r'(\d+)', raw_name)

        if qty_match:
            # Case 1: Quantity is explicitly in the string
            qty = float(qty_match.group(1))
            applied_rules.append("scharrelei_qty_from_name")

        elif 5.5 <= paid_amount <= 7.49:
            # Case 2: No quantity in string, but price implies a 20-pack (6.99 ± 0.50)
            qty = 20.0
            applied_rules.append("scharrelei_20pack_by_price")

        elif 2 <= paid_amount <= 3:
            # Case 3: No quantity in string, but price implies a 6-pack (2.49 ± 0.50)
            qty = 6.0
            applied_rules.append("scharrelei_6pack_by_price")

        # Standardize the product name regardless of which case triggered
        cleaned_name = 'SCHARRELEI'
        new_price = round(paid_amount / qty, 2) if qty else None

        return cleaned_name, qty, new_price, applied_rules

    # ============================================================
    # Skip cleaning for excluded items and items without numbers
    # ============================================================
    if raw_name in EXCLUDED_FROM_CLEANING or not re.findall(r"\d+", raw_name):
        return raw_name, qty, None, applied_rules

    # ============================================================
    # Edge Case 3: Mathematical Bundles (e.g., "10+2", "12X330")
    # ============================================================
    match_plus = re.search(r'(\d+)\s*\+\s*(\d+)', raw_name)
    if match_plus:
        applied_rules.append("clean_bundle_plus")
        qty = float(match_plus.group(1)) + float(match_plus.group(2))
        cleaned_name = raw_name[:match_plus.start()].strip()
        return cleaned_name, qty, None, applied_rules

    match_x = re.search(r'(\d+)\s*X\s*\d+', raw_name)
    if match_x:
        applied_rules.append("clean_bundle_x")
        qty = float(match_x.group(1))
        cleaned_name = raw_name[:match_x.start()].strip()
        return cleaned_name, qty, None, applied_rules

    # ============================================================
    # Edge Case 4: Pack Identifiers (ST, FL, BL, P, PK, ROL, RL, SC)
    # ============================================================
    # Captures formats like "6BL", "12P", "8ST", "12ROL"
    match_unit = re.search(r'(\d+)\s*(ST|FL|BL|P|PK|ROL|RL|SC)(?:\b|\s|$)', raw_name)
    if match_unit:
        applied_rules.append("clean_pack_identifier")
        qty = float(match_unit.group(1))

        # Clean the extracted unit from the item name
        cleaned_name = raw_name.replace(match_unit.group(0), '').strip()

        # Sub-cleaning for paper products: Remove layer counts (e.g., "4LGS", "3 LGS", "2LG")
        cleaned_name = re.sub(r'\d+\s*LGS?', '', cleaned_name).strip()

        # Sub-cleaning: Remove trailing 'P' artifacts left behind (e.g., from "6PK P")
        if cleaned_name.endswith(' P'):
            cleaned_name = cleaned_name[:-2].strip()

        return cleaned_name, qty, None, applied_rules

    # ============================================================
    # Edge Case 5: Trailing Prices & OCR Artifacts
    # ============================================================
    # Cleans appended prices like "HAM DUO P 3,75" or OCR artifacts like "COCA COLA 1,5]"
    match_trailing_num = re.search(r'\s+(\d+[,\.]\d{1,2})\]?$', raw_name)
    if match_trailing_num:
        applied_rules.append("clean_trailing_price")
        cleaned_name = raw_name[:match_trailing_num.start()].strip()
        return cleaned_name, qty, None, applied_rules

    # Default: Return AS-IS
    return raw_name, qty, None, applied_rules


def clean_item_name(item_name: str) -> str:
    """
    Clean item name by removing common artifacts.

    Combines multiple cleaning steps:
    - Remove trailing prices first (e.g., " 3,75")
    - Remove trailing 'P' (price-marked indicator)
    - Remove ' P' in middle followed by price-like patterns
    - Collapse multiple spaces

    Args:
        item_name: Raw item name

    Returns:
        Cleaned item name
    """
    if not item_name:
        return item_name

    name = str(item_name).strip()

    # Remove trailing prices FIRST (e.g., " 3,75" or " 1,5]")
    name = re.sub(r'\s+(\d+[,\.]\d{1,2})\]?$', '', name)

    # Remove trailing ' P' or ' P ' (price-marked indicator)
    name = re.sub(r'\s+P\s*$', '', name, flags=re.IGNORECASE)

    # Remove ' P' in middle (e.g., "HAM P DUO" -> "HAM DUO")
    name = re.sub(r'\s+P\s+(?=[A-Z])', ' ', name, flags=re.IGNORECASE)

    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()

    return name


def should_filter_item(item_name: str) -> bool:
    """
    Check if an item should be filtered out because it is not a product.

    Catches deposits (STATIEGELD/STATI), savings stamps (KOOPZEGELS),
    cashback/discount/payment lines (CASHBACK, KORTING, BEDRAG), and common
    variants such as "STATIEGELD FLES 0.25L".

    Args:
        item_name: Item name to check

    Returns:
        True if item should be filtered out
    """
    return is_non_product_item(item_name)
