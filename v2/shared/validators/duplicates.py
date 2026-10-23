"""
Duplicate detection: same item appearing multiple times on one receipt.
"""

from typing import List, Tuple


def detect_duplicates(items: List[dict]) -> Tuple[bool, List[Tuple[int, int, str]]]:
    """
    Detect duplicate items on a receipt.

    Two items are considered duplicates if they have:
    - Same item_name (case-insensitive)
    - Same line_total_paid_amount

    Args:
        items: List of item dicts

    Returns:
        Tuple of (has_duplicates, list_of_duplicate_pairs)
        Each pair is (index1, index2, item_name)
    """
    duplicates = []
    seen = {}  # (name_upper, total) -> first_index

    for i, item in enumerate(items):
        name = item.get("item_name", "").upper().strip()
        total = round(item.get("line_total_paid_amount", 0), 2)
        key = (name, total)

        if key in seen:
            duplicates.append((seen[key], i, item.get("item_name", "")))
        else:
            seen[key] = i

    return len(duplicates) > 0, duplicates
