"""
Shared non-product line guard for receipt items.

Some receipt lines are not purchasable grocery products:
- KOOPZEGELS: Albert Heijn savings stamps / discount coupons
- STATIEGELD: bottle/container deposits
- CASHBACK: cashback/payout lines
- KORTING: discount lines
- BEDRAG: amount/payment metadata lines

These must never enter product tables (processed_data, normalized_data,
classified_data) or the classification dictionary (item_labels), and they
must never be used as neighbours for embedding matching.

The matching is intentionally explicit and narrow:
- Exact names are matched case-insensitively after trimming whitespace.
- A small set of recognized non-product prefixes is also matched, so common
  variants such as "STATIEGELD FLES 0.25L" and "STATI 0.25" are caught.
- We do NOT broadly exclude substrings like "KORTING" or "BEDRAG" because
  those can legitimately occur inside real product names.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional


# Exact receipt-line names that are never grocery products.
EXACT_NON_PRODUCT_NAMES: frozenset[str] = frozenset(
    {
        "KOOPZEGELS",
        "KOOPZEGEL",
        "STATIEGELD",
        "CASHBACK",
        "KORTING",
        "BEDRAG",
    }
)

# Recognized non-product families. These are prefix matches on normalized
# uppercase text, not broad substring matches.
NON_PRODUCT_PREFIXES: tuple[str, ...] = (
    "STATIEGELD",
    "STATI ",
    "STATI",
)

# Human-readable reason used by Stage 2 and audit/debug output.
NON_PRODUCT_FILTER_REASON = "non_product_receipt_line"


def normalize_receipt_line_name(item_name: Optional[str]) -> str:
    """Return a normalized uppercase receipt-line name for guard matching."""
    if not item_name:
        return ""
    return re.sub(r"\s+", " ", str(item_name).strip()).upper()


def is_non_product_item(item_name: Optional[str]) -> bool:
    """
    Return True when a receipt line is a known non-product line.

    Args:
        item_name: Raw or normalized receipt item name.

    Returns:
        True if the line must be excluded from product tables and
        classification neighbours.
    """
    normalized = normalize_receipt_line_name(item_name)
    if not normalized:
        return False

    if normalized in EXACT_NON_PRODUCT_NAMES:
        return True

    return any(
        normalized == prefix.rstrip() or normalized.startswith(prefix)
        for prefix in NON_PRODUCT_PREFIXES
    )


def filter_non_product_items(item_names: Iterable[Optional[str]]) -> list[str]:
    """Return only names that are not known non-product receipt lines."""
    return [name for name in item_names if not is_non_product_item(name)]
