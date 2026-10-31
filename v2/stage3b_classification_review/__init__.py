"""
Stage 3B: Classification Review

Tools for reviewing and auditing product classifications:
- CLI for manual review (list, show, approve, set, taxonomy)
- Label validator to prevent invented categories/sub-categories
- Batch review queries for sub-agent audits
- Handoff documentation for automated review workflows

Usage:
    python -m v2.stage3b_classification_review.cli list
    python -m v2.stage3b_classification_review.cli taxonomy
    python -m v2.stage3b_classification_review.validator "Carnes" "Jamón"
    python -m v2.stage3b_classification_review.validator --list
    python -m v2.stage3b_classification_review.batch_review 0 50
"""

__version__ = "1.0.0"

# Lazy imports to avoid circular import warnings when running modules directly
def __getattr__(name):
    if name in ("validate_label", "validate_label_string", "suggest_correction", "list_taxonomy"):
        from v2.stage3b_classification_review import validator
        return getattr(validator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "validate_label",
    "validate_label_string",
    "suggest_correction",
    "list_taxonomy",
]
