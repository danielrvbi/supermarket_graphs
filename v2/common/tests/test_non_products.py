"""
Tests for the shared non-product receipt line guard.

Usage:
    python -m pytest v2/common/tests/test_non_products.py -v
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parents[2]))

from v2.common.non_products import (
    EXACT_NON_PRODUCT_NAMES,
    NON_PRODUCT_PREFIXES,
    filter_non_product_items,
    is_non_product_item,
    normalize_receipt_line_name,
)


def test_exact_non_product_names():
    """All approved exact names must be detected."""
    for name in ["KOOPZEGELS", "STATIEGELD", "CASHBACK", "KORTING", "BEDRAG"]:
        assert is_non_product_item(name), f"{name} should be non-product"
        assert is_non_product_item(name.lower()), f"{name.lower()} should be non-product"
        assert is_non_product_item(f"  {name}  "), f"padded {name} should be non-product"


def test_koopzegel_variant():
    """KOOPZEGEL (singular) is also a savings-stamp line."""
    assert is_non_product_item("KOOPZEGEL")
    assert is_non_product_item("koopzegel")


def test_statiegeld_variants():
    """Common deposit line variants must be detected."""
    assert is_non_product_item("STATIEGELD FLES 0.25L")
    assert is_non_product_item("STATIEGELD FLES")
    assert is_non_product_item("STATI 0.25")
    assert is_non_product_item("statiegeld fles 0.25l")


def test_normal_products_not_filtered():
    """Real grocery products must NOT be filtered."""
    products = [
        "COLA ZERO",
        "AH BIO KIPFI",
        "HEINEKEN 12P",
        "STEAK",
        "BEDRIJFSPET",
        "KORTIJKE BROODJES",  # Contains "KORT" but is not "KORTING"
        "BEDDENGOED SET",    # Contains "BED" but is not "BEDRAG"
        "CASHBACK CAFE",     # Contains "CASH" but is not exactly "CASHBACK"
    ]
    for name in products:
        assert not is_non_product_item(name), f"{name} should NOT be filtered"


def test_empty_and_none():
    """Empty/None names are not non-products (they fail elsewhere)."""
    assert not is_non_product_item("")
    assert not is_non_product_item(None)


def test_normalize_receipt_line_name():
    """Normalization collapses whitespace and uppercases."""
    assert normalize_receipt_line_name("  koopzegels  ") == "KOOPZEGELS"
    assert normalize_receipt_line_name("statiegeld   fles") == "STATIEGELD FLES"
    assert normalize_receipt_line_name(None) == ""
    assert normalize_receipt_line_name("") == ""


def test_filter_non_product_items():
    """Filter helper keeps products and drops non-products."""
    items = [
        "COLA ZERO",
        "KOOPZEGELS",
        "AH BIO KIPFI",
        "STATIEGELD FLES",
        "HEINEKEN",
        "CASHBACK",
        None,
        "",
    ]
    result = filter_non_product_items(items)
    assert result == ["COLA ZERO", "AH BIO KIPFI", "HEINEKEN", None, ""]


def test_constants_are_frozenset_and_tuple():
    """Constants should be immutable for safe sharing."""
    assert isinstance(EXACT_NON_PRODUCT_NAMES, frozenset)
    assert isinstance(NON_PRODUCT_PREFIXES, tuple)
    assert "KOOPZEGELS" in EXACT_NON_PRODUCT_NAMES
    assert "STATIEGELD" in EXACT_NON_PRODUCT_NAMES


if __name__ == "__main__":
    test_exact_non_product_names()
    test_koopzegel_variant()
    test_statiegeld_variants()
    test_normal_products_not_filtered()
    test_empty_and_none()
    test_normalize_receipt_line_name()
    test_filter_non_product_items()
    test_constants_are_frozenset_and_tuple()
    print("All non_products tests passed!")
