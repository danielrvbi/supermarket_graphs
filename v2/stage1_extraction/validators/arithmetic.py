"""
Arithmetic validation: quantity × unit_price ≈ line_total

NOTE: This is a WARNING-ONLY check. It does NOT fail validation.
Many receipts have complex pricing (bundles, weighted items, rounding)
that doesn't follow simple arithmetic.

For weight items (weight_in_grams):
- measurement_quantity is in grams
- price_per_measurement_unit is price per KG
- So: (quantity / 1000) × price_per_kg ≈ line_total

For discrete items:
- measurement_quantity is number of units
- price_per_measurement_unit is price per unit
- So: quantity × price_per_unit ≈ line_total
"""

from typing import List, Tuple
from v2.common.settings import settings


def check_arithmetic(items: List[dict]) -> Tuple[bool, List[str]]:
    """
    Check arithmetic as a WARNING only (never fails validation).

    Returns:
        Tuple of (all_ok, list_of_warnings)
    """
    warnings = []
    tolerance = settings.ARITHMETIC_TOLERANCE

    for i, item in enumerate(items):
        item_name = item.get("item_name", f"item_{i}")
        quantity = item.get("measurement_quantity")
        unit_price = item.get("price_per_measurement_unit")
        line_total = item.get("line_total_paid_amount")
        measurement_type = item.get("measurement_type", "discrete_units")

        # Skip if any value is missing
        if quantity is None or unit_price is None or line_total is None:
            continue

        # Calculate expected total based on measurement type
        if measurement_type == "weight_in_grams":
            # Price is per KG, quantity is in grams
            calculated = (quantity / 1000.0) * unit_price
            calc_desc = f"({quantity}g / 1000) × €{unit_price}/kg"
        else:
            # Discrete units: quantity × price_per_unit = total
            calculated = quantity * unit_price
            calc_desc = f"{quantity} × €{unit_price}"

        diff = abs(calculated - line_total)

        if diff > tolerance:
            warnings.append(
                f"Arithmetic mismatch (warning only): '{item_name}': {calc_desc} = €{calculated:.2f} "
                f"≠ €{line_total:.2f} (diff: €{diff:.2f})"
            )

    return len(warnings) == 0, warnings


# Backward compatibility alias
validate_arithmetic = check_arithmetic
