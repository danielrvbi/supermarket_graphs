"""
Item name standardization rules.

Ported from V1: item_name.str.strip().str.upper()
"""

import re
from typing import List


def standardize_item_name(name: str) -> str:
    """
    Standardize item name: strip whitespace and uppercase.

    Args:
        name: Raw item name from receipt

    Returns:
        Standardized item name
    """
    if not name:
        return ""
    return str(name).strip().upper()


def remove_trailing_price_artifacts(name: str) -> str:
    """
    Remove trailing prices and OCR artifacts from item names.

    Examples:
        "HAM DUO P 3,75" -> "HAM DUO"
        "COCA COLA 1,5]" -> "COCA COLA"

    Ported from V1 _clean_single_row() Edge Case 5.
    """
    if not name:
        return name

    # Remove trailing price patterns like " 3,75" or " 1,5]"
    match_trailing_num = re.search(r'\s+(\d+[,\.]\d{1,2})\]?$', name)
    if match_trailing_num:
        return name[:match_trailing_num.start()].strip()

    return name


def remove_pack_artifacts(name: str) -> str:
    """
    Remove pack-related artifacts from item names.

    Examples:
        "6BL" -> ""
        "12P" -> ""
        "8ST" -> ""

    Returns cleaned name without pack identifiers.
    """
    if not name:
        return name

    # Remove pack identifiers: digits followed by ST, FL, BL, P, PK, ROL, RL, SC
    cleaned = re.sub(r'\d+\s*(ST|FL|BL|P|PK|ROL|RL|SC)(?:\b|\s|$)', '', name, flags=re.IGNORECASE)

    # Remove layer counts for paper products: "4LGS", "3 LGS", "2LG"
    cleaned = re.sub(r'\d+\s*LGS?', '', cleaned, flags=re.IGNORECASE)

    # Remove trailing 'P' artifacts (e.g., from "6PK P")
    if cleaned.endswith(' P'):
        cleaned = cleaned[:-2].strip()

    return cleaned.strip()
