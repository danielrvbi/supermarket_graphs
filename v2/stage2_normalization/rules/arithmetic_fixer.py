"""
Arithmetic fixing rules.

Ported from V1:
- AH: Fix cases where price_per_measurement_unit == line_total_paid_amount but quantity != 1
- AH: Recalculate measurement_quantity when qty × price != line_total
- Jumbo: Calculate price_per_measurement_unit = line_total / quantity
"""

from typing import Optional, Tuple


def recalc_price_per_unit(
    line_total: Optional[float],
    quantity: Optional[float]
) -> Optional[float]:
    """
    Calculate price per measurement unit from line total and quantity.

    Ported from V1 Jumbo:
        price_per_measurement_unit = lambda df: df["line_total_paid_amount"].div(df["measurement_quantity"])

    Args:
        line_total: Total amount paid for the line item
        quantity: Measurement quantity (already normalized)

    Returns:
        Price per measurement unit, or None if calculation impossible
    """
    if line_total is None or quantity is None or quantity == 0:
        return None
    return float(line_total) / float(quantity)


def fix_arithmetic(
    quantity: Optional[float],
    price_per_unit: Optional[float],
    line_total: Optional[float],
    measurement_type: str = "discrete_units",
    tolerance: float = 0.05
) -> Tuple[Optional[float], Optional[float], Optional[float], list]:
    """
    Fix arithmetic inconsistencies in item data.

    Ported from V1 AH fixes (lines 81-115):

    Case 1: price_per_unit == line_total but quantity != 1
        → line_total should be quantity × price_per_unit

    Case 2: quantity × price_per_unit != line_total (diff > tolerance)
        → recalculate quantity = line_total / price_per_unit

    Args:
        quantity: Measurement quantity (already normalized to kg for weights)
        price_per_unit: Price per measurement unit
        line_total: Total amount paid
        measurement_type: "discrete_units" or "weight_in_grams"
        tolerance: Maximum allowed difference before triggering fix

    Returns:
        Tuple of (fixed_quantity, fixed_price_per_unit, fixed_line_total, applied_rules)
    """
    applied_rules = []

    # Ensure all values are floats
    qty = float(quantity) if quantity is not None else None
    ppu = float(price_per_unit) if price_per_unit is not None else None
    total = float(line_total) if line_total is not None else None

    # Can't fix if any value is missing
    if qty is None or ppu is None or total is None:
        return qty, ppu, total, applied_rules

    # Case 1: price_per_unit == line_total but quantity != 1
    # This happens when the receipt shows unit price = total (for single items)
    # but the quantity is not 1
    if abs(ppu - total) < 0.001 and abs(qty - 1.0) > 0.001:
        # Fix: line_total should be quantity × price_per_unit
        fixed_total = qty * ppu
        applied_rules.append("fix_line_total_from_qty_times_price")
        return qty, ppu, round(fixed_total, 3), applied_rules

    # Case 2: quantity × price_per_unit != line_total
    calculated_total = qty * ppu
    diff = abs(calculated_total - total)

    if diff > tolerance:
        # Recalculate quantity from line_total and price_per_unit
        if ppu != 0:
            fixed_qty = total / ppu
            applied_rules.append("fix_quantity_from_total_div_price")
            return round(fixed_qty, 3), ppu, total, applied_rules

    # No fix needed
    return qty, ppu, total, applied_rules
