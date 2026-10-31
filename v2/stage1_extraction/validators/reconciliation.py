"""
Reconciliation validation: sum of items ≈ receipt total

NOTE: This is DISABLED by default. Receipt totals are often wrong or
incomplete due to hidden discounts, loyalty savings, etc.

The goal of this pipeline is ONLY to extract item rows with their prices,
NOT to validate that the sum matches the receipt total.
"""

from typing import List, Optional, Tuple


def reconcile_total(
    items: List[dict],
    receipt_total: Optional[float],
    exclude_items: Optional[List[str]] = None,
) -> Tuple[bool, float, Optional[str]]:
    """
    DEPRECATED: Reconciliation is no longer used for validation.

    Kept for backward compatibility but always returns success.

    Returns:
        Tuple of (True, calculated_sum, None)
    """
    calculated = sum(
        item.get("line_total_paid_amount", 0)
        for item in items
    )
    return True, calculated, None


def get_sum(items: List[dict]) -> float:
    """Calculate sum of item totals (informational only)."""
    return sum(item.get("line_total_paid_amount", 0) for item in items)
