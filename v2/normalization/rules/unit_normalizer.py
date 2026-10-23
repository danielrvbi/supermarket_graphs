"""
Unit normalization rules.

Ported from V1:
- Convert weight_in_grams to kg (divide by 1000)
- Ensure measurement_quantity is float
"""

from typing import Optional


def normalize_measurement_quantity(
    quantity: Optional[float],
    measurement_type: str
) -> Optional[float]:
    """
    Normalize measurement quantity based on measurement type.

    For weight_in_grams: convert grams to kg (divide by 1000)
    For discrete_units: keep as-is

    Ported from V1:
        measurement_quantity = lambda df: np.where(
            df["measurement_type"].eq("weight_in_grams"),
            df["measurement_quantity"].div(1000),
            df["measurement_quantity"]
        )

    Args:
        quantity: Raw measurement quantity
        measurement_type: "discrete_units" or "weight_in_grams"

    Returns:
        Normalized quantity (kg for weights, as-is for discrete)
    """
    if quantity is None:
        return None

    qty = float(quantity)

    if measurement_type == "weight_in_grams":
        # Convert grams to kg
        return qty / 1000.0

    return qty


def normalize_price_per_unit_for_weight(
    price_per_unit: Optional[float],
    measurement_type: str
) -> Optional[float]:
    """
    Ensure price_per_measurement_unit is consistent with normalized quantity.

    For weight_in_grams:
    - After converting quantity from g to kg, price_per_unit should be per kg
    - The price_per_unit from receipt is already per kg, so no change needed

    For discrete_units:
    - price_per_unit is per unit, no change needed

    Args:
        price_per_unit: Price per measurement unit
        measurement_type: "discrete_units" or "weight_in_grams"

    Returns:
        Price per unit (unchanged, but validated as float)
    """
    if price_per_unit is None:
        return None
    return float(price_per_unit)
