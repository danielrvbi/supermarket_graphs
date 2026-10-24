#!/usr/bin/env python3
"""
Backwards-compatible shim for the label validator.

This script has been moved to v2.stage3b_classification_review.validator.

Usage:
    python scripts/validate_label.py "Carnes" "Jamón"
    python -m v2.stage3b_classification_review.validator "Carnes" "Jamón"  # preferred
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[1]))

from v2.stage3b_classification_review.validator import *  # noqa: F401,F403
from v2.stage3b_classification_review.validator import main


if __name__ == "__main__":
    sys.exit(main())
