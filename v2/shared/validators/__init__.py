"""Deterministic validation rules shared across pipelines.

NOTE: Only schema and sanity checks are used for validation.
Reconciliation and arithmetic checks are warnings-only.
"""

from v2.shared.validators.arithmetic import check_arithmetic
from v2.shared.validators.reconciliation import get_sum
from v2.shared.validators.duplicates import detect_duplicates
from v2.shared.validators.sanity import sanity_check_items, validate_date

__all__ = [
    "check_arithmetic",
    "get_sum",
    "detect_duplicates",
    "sanity_check_items",
    "validate_date",
]

# Backward compatibility
from v2.shared.validators.arithmetic import validate_arithmetic
from v2.shared.validators.reconciliation import reconcile_total
