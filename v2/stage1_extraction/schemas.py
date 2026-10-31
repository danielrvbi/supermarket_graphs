"""
V1-compatible output schemas.

These match the exact schema used in v1 for backward compatibility:
- RawItem: item_name, measurement_type, measurement_quantity, 
            price_per_measurement_unit, line_total_paid_amount
- RawReceipt: date_of_purchase, items
"""

from pydantic import BaseModel, Field
from typing import Literal, List, Optional


class RawItem(BaseModel):
    """A single item from a receipt. Same schema as v1."""

    item_name: str = Field(description="Product name as written on receipt")
    measurement_type: Literal["discrete_units", "weight_in_grams"] = Field(
        description="Type of measurement: discrete units or weight in grams"
    )
    measurement_quantity: float = Field(
        description="Quantity: number of units, or weight in grams"
    )
    price_per_measurement_unit: Optional[float] = Field(
        default=None,
        description="Price per unit (per piece or per kg). Null if not visible on receipt."
    )
    line_total_paid_amount: float = Field(
        description="Total amount paid for this line item"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "item_name": "COLA ZERO FL",
                "measurement_type": "discrete_units",
                "measurement_quantity": 3.0,
                "price_per_measurement_unit": 1.79,
                "line_total_paid_amount": 5.37
            }
        }


class RawReceipt(BaseModel):
    """A complete receipt. Same schema as v1."""

    date_of_purchase: str = Field(
        description="Purchase date. Format varies: 'YYYY/MM/DD' for AH, Dutch text for Jumbo"
    )
    items: List[RawItem] = Field(description="List of purchased items")

    class Config:
        json_schema_extra = {
            "example": {
                "date_of_purchase": "2026/05/11",
                "items": [
                    {
                        "item_name": "COLA ZERO FL",
                        "measurement_type": "discrete_units",
                        "measurement_quantity": 3.0,
                        "price_per_measurement_unit": 1.79,
                        "line_total_paid_amount": 5.37
                    }
                ]
            }
        }


def items_to_receipt_dict(items: List[dict], date_of_purchase: str) -> dict:
    """
    Convert a list of item dicts to a RawReceipt-compatible dict.

    Args:
        items: List of dicts with item fields
        date_of_purchase: Date string

    Returns:
        Dict matching RawReceipt schema
    """
    return {
        "date_of_purchase": date_of_purchase,
        "items": items
    }
