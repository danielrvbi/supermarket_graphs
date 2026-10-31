"""
Sanity checks: price ranges, date validation, quantity validation.
"""

from typing import List, Tuple, Optional
from datetime import datetime, date


def sanity_check_items(items: List[dict]) -> Tuple[bool, List[str]]:
    """
    Perform sanity checks on extracted items.

    Checks:
    - Prices are positive and reasonable (< €100 per line)
    - Quantities are positive
    - Weight items have reasonable weights (1g - 10kg)

    Args:
        items: List of item dicts

    Returns:
        Tuple of (all_passed, list_of_warnings)
    """
    warnings = []

    for i, item in enumerate(items):
        item_name = item.get("item_name", f"item_{i}")
        quantity = item.get("measurement_quantity", 0)
        line_total = item.get("line_total_paid_amount", 0)
        unit_price = item.get("price_per_measurement_unit")
        measurement_type = item.get("measurement_type", "discrete_units")

        # Check quantity is positive
        if quantity is not None and quantity <= 0:
            warnings.append(f"Item '{item_name}': non-positive quantity ({quantity})")

        # Check line total is reasonable
        if line_total is not None:
            if line_total < 0:
                warnings.append(f"Item '{item_name}': negative price ({line_total})")
            elif line_total > 100:
                warnings.append(f"Item '{item_name}': unusually high price (€{line_total})")

        # Check unit price is reasonable
        if unit_price is not None:
            if unit_price < 0:
                warnings.append(f"Item '{item_name}': negative unit price ({unit_price})")
            elif unit_price > 100:
                warnings.append(f"Item '{item_name}': unusually high unit price (€{unit_price})")

        # Check weight items
        if measurement_type == "weight_in_grams" and quantity is not None:
            if quantity < 1:
                warnings.append(f"Item '{item_name}': weight too small ({quantity}g)")
            elif quantity > 10000:  # 10kg
                warnings.append(f"Item '{item_name}': weight too large ({quantity}g)")

    return len(warnings) == 0, warnings


def validate_date(
    date_str: str,
    min_date: Optional[date] = None,
    max_date: Optional[date] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Validate a date string is reasonable.

    Args:
        date_str: Date string in various formats
        min_date: Earliest acceptable date (default: 2020-01-01)
        max_date: Latest acceptable date (default: today + 1 day)

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not date_str:
        return False, "Date is empty"

    min_date = min_date or date(2020, 1, 1)
    max_date = max_date or date.today()

    # Try to parse various formats
    parsed = _parse_date_flexible(date_str)

    if parsed is None:
        return False, f"Could not parse date: '{date_str}'"

    if parsed < min_date:
        return False, f"Date {parsed} is before minimum {min_date}"

    if parsed > max_date:
        return False, f"Date {parsed} is in the future (max {max_date})"

    return True, None


def _parse_date_flexible(date_str: str) -> Optional[date]:
    """Try to parse a date string in various formats."""
    date_str = date_str.strip()

    # Dutch month mapping
    dutch_months = {
        "januari": 1, "februari": 2, "maart": 3, "april": 4,
        "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
        "september": 9, "oktober": 10, "november": 11, "december": 12,
    }

    # Try ISO format: YYYY/MM/DD or YYYY-MM-DD
    for fmt in ["%Y/%m/%d", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y"]:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass

    # Try Dutch format: "Dinsdag 12 mei 2026" or "12 mei 2026"
    import re
    match = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", date_str.lower())
    if match:
        day, month_name, year = match.groups()
        month = dutch_months.get(month_name)
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                pass

    return None
