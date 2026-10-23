"""
Deterministic normalization module for V2 pipeline.

Reads raw extracted data from processed_data table and applies
rule-based cleaning to produce normalized_data table.

No LLM calls - 100% deterministic.
"""

from v2.normalization.normalizer import Normalizer, normalize_item
from v2.normalization.rules.item_cleaner import clean_item_name, apply_edge_cases
from v2.normalization.rules.date_parser import parse_dutch_date, standardize_date
from v2.normalization.rules.unit_normalizer import normalize_measurement_quantity
from v2.normalization.rules.arithmetic_fixer import fix_arithmetic, recalc_price_per_unit
from v2.normalization.rules.name_standardizer import standardize_item_name

__all__ = [
    "Normalizer",
    "normalize_item",
    "clean_item_name",
    "apply_edge_cases",
    "parse_dutch_date",
    "standardize_date",
    "normalize_measurement_quantity",
    "fix_arithmetic",
    "recalc_price_per_unit",
    "standardize_item_name",
]
