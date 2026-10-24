"""
Backwards-compatible shim for the review CLI.

This module has been moved to v2.stage3b_classification_review.cli.

Usage:
    python -m v2.stage3_classification.review.cli list
    python -m v2.stage3b_classification_review.cli list  # preferred
"""

import sys

# Re-export everything from the new location
from v2.stage3b_classification_review.cli import *  # noqa: F401,F403
from v2.stage3b_classification_review.cli import main


if __name__ == "__main__":
    main()
