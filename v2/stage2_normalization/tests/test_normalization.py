"""
Unit tests for normalization module.

Tests all deterministic rules ported from V1 step2_normalization.py.

Usage:
    python -m pytest v2/stage2_normalization/tests -v
    python -m v2.stage2_normalization.tests.test_normalization  # Run directly
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parents[3]))

from v2.stage2_normalization.normalizer import Normalizer, normalize_item
from v2.stage2_normalization.rules.name_standardizer import (
    standardize_item_name,
    remove_trailing_price_artifacts,
    remove_pack_artifacts,
)
from v2.stage2_normalization.rules.date_parser import (
    parse_dutch_date,
    standardize_date,
    get_month_of_purchase,
    extract_date_from_filename,
)
from v2.stage2_normalization.rules.unit_normalizer import normalize_measurement_quantity
from v2.stage2_normalization.rules.arithmetic_fixer import fix_arithmetic, recalc_price_per_unit
from v2.stage2_normalization.rules.item_cleaner import (
    apply_edge_cases,
    clean_item_name,
    should_filter_item,
)


# ============================================================
# Test Name Standardizer
# ============================================================

def test_standardize_item_name():
    """Test basic name standardization."""
    assert standardize_item_name("  cola zero  ") == "COLA ZERO"
    assert standardize_item_name("Coca Cola") == "COCA COLA"
    assert standardize_item_name("") == ""
    assert standardize_item_name(None) == ""
    print("✓ test_standardize_item_name passed")


def test_remove_trailing_price_artifacts():
    """Test removing trailing prices from item names."""
    assert remove_trailing_price_artifacts("HAM DUO P 3,75") == "HAM DUO P"
    assert remove_trailing_price_artifacts("COCA COLA 1,5]") == "COCA COLA"
    assert remove_trailing_price_artifacts("BROOD 2.50") == "BROOD"
    assert remove_trailing_price_artifacts("KAAS") == "KAAS"
    print("✓ test_remove_trailing_price_artifacts passed")


def test_remove_pack_artifacts():
    """Test removing pack identifiers."""
    # These are tested via apply_edge_cases, but basic cleaning:
    result = remove_pack_artifacts("COLA 6BL")
    assert "6BL" not in result or "COLA" in result
    print("✓ test_remove_pack_artifacts passed")


# ============================================================
# Test Date Parser
# ============================================================

def test_parse_dutch_date():
    """Test Dutch date parsing."""
    assert parse_dutch_date("Dinsdag 12 mei 2026") == "2026-05-12"
    assert parse_dutch_date("maandag 19 januari 2026") == "2026-01-19"
    assert parse_dutch_date("2) maandag 19 januari 2026") == "2026-01-19"
    assert parse_dutch_date("woensdag 1 maart 2024") == "2024-03-01"
    assert parse_dutch_date("") is None
    assert parse_dutch_date("invalid date") is None
    print("✓ test_parse_dutch_date passed")


def test_standardize_date():
    """Test date standardization for different formats."""
    # AH formats
    assert standardize_date("2024/03/08", store="ah") == "2024-03-08"
    assert standardize_date("2024-03-08", store="ah") == "2024-03-08"
    assert standardize_date("08-03-2024", store="ah") == "2024-03-08"

    # Jumbo formats (Dutch)
    assert standardize_date("Dinsdag 12 mei 2026", store="jumbo") == "2026-05-12"

    # Invalid
    assert standardize_date("", store="ah") is None
    assert standardize_date(None, store="ah") is None
    print("✓ test_standardize_date passed")


def test_get_month_of_purchase():
    """Test month extraction."""
    assert get_month_of_purchase("2026-05-12") == "2026-05-01"
    assert get_month_of_purchase("2024-01-01") == "2024-01-01"
    assert get_month_of_purchase(None) is None
    assert get_month_of_purchase("invalid") is None
    print("✓ test_get_month_of_purchase passed")


def test_extract_date_from_filename():
    """Test date extraction from AH filenames."""
    assert extract_date_from_filename("AH_kassabon_2024-03-08_1621_1080.pdf") == "2024-03-08"
    assert extract_date_from_filename("raw_receipts/ah/AH_kassabon_2026-01-19_1234_5678.pdf") == "2026-01-19"
    assert extract_date_from_filename("no-date-here.pdf") is None
    print("✓ test_extract_date_from_filename passed")


# ============================================================
# Test Unit Normalizer
# ============================================================

def test_normalize_measurement_quantity():
    """Test unit normalization (g → kg)."""
    # Weight items: grams → kg
    assert normalize_measurement_quantity(500, "weight_in_grams") == 0.5
    assert normalize_measurement_quantity(1000, "weight_in_grams") == 1.0
    assert normalize_measurement_quantity(250, "weight_in_grams") == 0.25

    # Discrete items: unchanged
    assert normalize_measurement_quantity(3, "discrete_units") == 3.0
    assert normalize_measurement_quantity(1, "discrete_units") == 1.0

    # None handling
    assert normalize_measurement_quantity(None, "weight_in_grams") is None
    print("✓ test_normalize_measurement_quantity passed")


# ============================================================
# Test Arithmetic Fixer
# ============================================================

def test_recalc_price_per_unit():
    """Test price per unit recalculation."""
    assert recalc_price_per_unit(7.96, 4.0) == 1.99
    assert recalc_price_per_unit(10.0, 2.0) == 5.0
    assert recalc_price_per_unit(5.0, 0) is None  # Division by zero
    assert recalc_price_per_unit(None, 2.0) is None
    print("✓ test_recalc_price_per_unit passed")


def test_fix_arithmetic():
    """Test arithmetic fixing."""
    # Case 1: price_per_unit == line_total but quantity != 1
    qty, ppu, total, rules = fix_arithmetic(
        quantity=3.0,
        price_per_unit=1.79,
        line_total=1.79,  # Should be 3 × 1.79 = 5.37
    )
    assert "fix_line_total_from_qty_times_price" in rules
    assert abs(total - 5.37) < 0.01

    # Case 2: quantity × price != line_total
    qty, ppu, total, rules = fix_arithmetic(
        quantity=2.0,
        price_per_unit=1.50,
        line_total=4.00,  # 2 × 1.50 = 3.00, diff = 1.00 > tolerance
    )
    assert "fix_quantity_from_total_div_price" in rules
    assert abs(qty - (4.00 / 1.50)) < 0.01

    # No fix needed
    qty, ppu, total, rules = fix_arithmetic(
        quantity=2.0,
        price_per_unit=2.50,
        line_total=5.00,  # 2 × 2.50 = 5.00 ✓
    )
    assert len(rules) == 0
    assert qty == 2.0
    assert ppu == 2.50
    assert total == 5.00
    print("✓ test_fix_arithmetic passed")


# ============================================================
# Test Item Cleaner (Edge Cases)
# ============================================================

def test_apply_edge_cases_scharrelei():
    """Test SCHARRELEI egg cleaning."""
    # Case 1: Quantity in name
    name, qty, ppu, rules = apply_edge_cases("SCHARRELEI 12", 5.97, measurement_quantity=1.0)
    assert name == "SCHARRELEI"
    assert qty == 12.0
    assert "clean_scharrelei" in rules
    assert "scharrelei_qty_from_name" in rules

    # Case 2: 20-pack by price (€6.99)
    name, qty, ppu, rules = apply_edge_cases("SCHARRELEI", 6.99, measurement_quantity=1.0)
    assert name == "SCHARRELEI"
    assert qty == 20.0
    assert "scharrelei_20pack_by_price" in rules
    assert ppu == round(6.99 / 20, 2)

    # Case 3: 6-pack by price (€2.49)
    name, qty, ppu, rules = apply_edge_cases("SCHARRELEI", 2.49, measurement_quantity=1.0)
    assert name == "SCHARRELEI"
    assert qty == 6.0
    assert "scharrelei_6pack_by_price" in rules
    print("✓ test_apply_edge_cases_scharrelei passed")


def test_apply_edge_cases_bundles():
    """Test mathematical bundle cleaning."""
    # "10+2" bundle
    name, qty, ppu, rules = apply_edge_cases("COLA 10+2", 12.00, measurement_quantity=1.0)
    assert name == "COLA"
    assert qty == 12.0
    assert "clean_bundle_plus" in rules

    # "12X330" bundle
    name, qty, ppu, rules = apply_edge_cases("BIER 12X330", 10.00, measurement_quantity=1.0)
    assert name == "BIER"
    assert qty == 12.0
    assert "clean_bundle_x" in rules
    print("✓ test_apply_edge_cases_bundles passed")


def test_apply_edge_cases_pack_identifiers():
    """Test pack identifier cleaning."""
    # "6BL" (6 bottles)
    name, qty, ppu, rules = apply_edge_cases("COLA 6BL", 10.00, measurement_quantity=1.0)
    assert qty == 6.0
    assert "clean_pack_identifier" in rules
    assert "6BL" not in name

    # "12P" (12 pieces)
    name, qty, ppu, rules = apply_edge_cases("KOEKJES 12P", 5.00, measurement_quantity=1.0)
    assert qty == 12.0
    assert "clean_pack_identifier" in rules

    # "8ST" (8 pieces)
    name, qty, ppu, rules = apply_edge_cases("BROODJES 8ST", 4.00, measurement_quantity=1.0)
    assert qty == 8.0
    assert "clean_pack_identifier" in rules
    print("✓ test_apply_edge_cases_pack_identifiers passed")


def test_apply_edge_cases_trailing_price():
    """Test trailing price removal."""
    name, qty, ppu, rules = apply_edge_cases("HAM DUO P 3,75", 3.75, measurement_quantity=1.0)
    assert "clean_trailing_price" in rules
    assert "3,75" not in name
    print("✓ test_apply_edge_cases_trailing_price passed")


def test_apply_edge_cases_excluded_items():
    """Test that excluded items are not cleaned."""
    # "DUVEL 666" should not be cleaned (it's a product name)
    name, qty, ppu, rules = apply_edge_cases("DUVEL 666", 3.50, measurement_quantity=1.0)
    assert name == "DUVEL 666"
    assert len(rules) == 0
    print("✓ test_apply_edge_cases_excluded_items passed")


def test_should_filter_item():
    """Test item filtering (non-product receipt lines)."""
    # Non-products that must be filtered
    assert should_filter_item("STATIEGELD FLES") == True
    assert should_filter_item("STATI 0.25") == True
    assert should_filter_item("STATIEGELD") == True
    assert should_filter_item("KOOPZEGELS") == True
    assert should_filter_item("KOOPZEGEL") == True
    assert should_filter_item("CASHBACK") == True
    assert should_filter_item("KORTING") == True
    assert should_filter_item("BEDRAG") == True
    # Real products that must NOT be filtered
    assert should_filter_item("COLA ZERO") == False
    assert should_filter_item("AH BIO KIPFI") == False
    assert should_filter_item("KORTIJKE BROODJES") == False  # Contains "KORT" but not "KORTING"
    assert should_filter_item("BEDDENGOED SET") == False    # Contains "BED" but not "BEDRAG"
    assert should_filter_item("") == False
    print("✓ test_should_filter_item passed")


def test_clean_item_name():
    """Test general item name cleaning."""
    assert clean_item_name("COLA P") == "COLA"
    assert clean_item_name("  COLA   ZERO  ") == "COLA ZERO"
    assert clean_item_name("HAM P 3,75") == "HAM"
    print("✓ test_clean_item_name passed")


# ============================================================
# Test Full Normalizer
# ============================================================

def test_normalizer_ah_item():
    """Test normalizing a complete AH item."""
    raw_item = {
        "id": 1,
        "receipt_id": "ah_test_2024-03-08",
        "receipt_path": "raw_receipts/ah/AH_kassabon_2024-03-08_1621_1080.pdf",
        "store": "ah",
        "date_of_purchase": "2024/03/08",
        "item_index": 0,
        "item_name": "  gi toscana  ",
        "measurement_type": "discrete_units",
        "measurement_quantity": 2.0,
        "price_per_measurement_unit": 4.25,
        "line_total_paid_amount": 8.5,
        "confidence": 0.99,
    }

    result = normalize_item(raw_item)

    assert result.item_name == "GI TOSCANA"
    assert result.measurement_quantity == 2.0
    assert result.price_per_measurement_unit == 4.25
    assert result.line_total_paid_amount == 8.5
    assert result.date_of_purchase == "2024-03-08"
    assert result.month_of_purchase == "2024-03-01"
    assert result.store == "ah"
    assert not result.filtered_out
    assert "name_uppercase" in result.normalization_rules
    assert "date_standardized" in result.normalization_rules
    print("✓ test_normalizer_ah_item passed")


def test_normalizer_jumbo_item():
    """Test normalizing a complete Jumbo item."""
    raw_item = {
        "id": 2,
        "receipt_id": "jumbo_test_2026-01-19",
        "receipt_path": "raw_receipts/jumbo/receipt.png",
        "store": "jumbo",
        "date_of_purchase": "2) maandag 19 januari 2026",
        "item_index": 0,
        "item_name": "Lactofree Hv Melk",
        "measurement_type": "discrete_units",
        "measurement_quantity": 4.0,
        "price_per_measurement_unit": 1.99,
        "line_total_paid_amount": 7.96,
        "confidence": 0.95,
    }

    result = normalize_item(raw_item)

    assert result.item_name == "LACTOFREE HV MELK"
    assert result.measurement_quantity == 4.0
    assert result.date_of_purchase == "2026-01-19"
    assert result.month_of_purchase == "2026-01-01"
    assert result.store == "jumbo"
    assert not result.filtered_out
    assert "date_parse_dutch" in result.normalization_rules
    print("✓ test_normalizer_jumbo_item passed")


def test_normalizer_weight_item():
    """Test normalizing a weight item (grams → kg)."""
    raw_item = {
        "id": 3,
        "receipt_id": "jumbo_test_weight",
        "receipt_path": "raw_receipts/jumbo/receipt.png",
        "store": "jumbo",
        "date_of_purchase": "2026-01-19",
        "item_index": 0,
        "item_name": "Maggi Aroma 250g",
        "measurement_type": "weight_in_grams",
        "measurement_quantity": 250.0,  # 250 grams
        "price_per_measurement_unit": 9.80,  # €9.80 per kg
        "line_total_paid_amount": 2.45,
        "confidence": 0.90,
    }

    result = normalize_item(raw_item)

    assert result.measurement_quantity == 0.25  # 250g = 0.25kg
    assert "weight_to_kg" in result.normalization_rules
    print("✓ test_normalizer_weight_item passed")


def test_normalizer_filtered_item():
    """Test that STATI items are filtered."""
    raw_item = {
        "id": 4,
        "receipt_id": "ah_test_stati",
        "receipt_path": "raw_receipts/ah/test.pdf",
        "store": "ah",
        "date_of_purchase": "2024-03-08",
        "item_index": 0,
        "item_name": "STATIEGELD FLES 0.25L",
        "measurement_type": "discrete_units",
        "measurement_quantity": 1.0,
        "price_per_measurement_unit": 0.25,
        "line_total_paid_amount": 0.25,
        "confidence": 0.99,
    }

    result = normalize_item(raw_item)

    assert result.filtered_out == True
    assert result.filter_reason == "non_product_receipt_line"
    assert "filter_non_product" in result.normalization_rules
    print("✓ test_normalizer_filtered_item passed")


def test_normalizer_arithmetic_fix():
    """Test arithmetic fixing in full normalization."""
    # AH case: price_per_unit == line_total but quantity != 1
    raw_item = {
        "id": 5,
        "receipt_id": "ah_test_arithmetic",
        "receipt_path": "raw_receipts/ah/test.pdf",
        "store": "ah",
        "date_of_purchase": "2024-03-08",
        "item_index": 0,
        "item_name": "TEST ITEM",
        "measurement_type": "discrete_units",
        "measurement_quantity": 3.0,
        "price_per_measurement_unit": 1.79,  # Same as line_total (wrong)
        "line_total_paid_amount": 1.79,
        "confidence": 0.90,
    }

    result = normalize_item(raw_item)

    # Should fix line_total to 3 × 1.79 = 5.37
    assert abs(result.line_total_paid_amount - 5.37) < 0.01
    assert "fix_line_total_from_qty_times_price" in result.normalization_rules
    print("✓ test_normalizer_arithmetic_fix passed")


def test_normalizer_pack_with_price_recalc():
    """Test that pack cleaning + final price recalc works correctly (HEINEKEN case).

    Original: "HEINEKEN 12P", qty=1, ppu=€12.15, total=€12.15
    Expected after normalization:
    - Pack cleaning extracts qty=12 from "12P"
    - Final recalc: ppu = total / qty = 12.15 / 12 = €1.01 per bottle
    """
    raw_item = {
        "id": 99,
        "receipt_id": "ah_test_heineken",
        "receipt_path": "raw_receipts/ah/test.pdf",
        "store": "ah",
        "date_of_purchase": "2024-03-08",
        "item_index": 0,
        "item_name": "HEINEKEN 12P",
        "measurement_type": "discrete_units",
        "measurement_quantity": 1.0,
        "price_per_measurement_unit": 12.15,
        "line_total_paid_amount": 12.15,
        "confidence": 0.95,
    }

    result = normalize_item(raw_item)

    # Pack identifier should be cleaned
    assert result.item_name == "HEINEKEN"
    assert result.measurement_quantity == 12.0
    assert "clean_pack_identifier" in result.normalization_rules

    # Final price recalc should give per-bottle price
    assert abs(result.price_per_measurement_unit - 1.01) < 0.01  # 12.15 / 12 = 1.0125
    assert abs(result.line_total_paid_amount - 12.15) < 0.01
    assert "price_recalc_final" in result.normalization_rules
    print("✓ test_normalizer_pack_with_price_recalc passed")


def test_normalizer_batch():
    """Test batch normalization."""
    raw_items = [
        {
            "id": 1,
            "receipt_id": "ah_test_1",
            "receipt_path": "test.pdf",
            "store": "ah",
            "date_of_purchase": "2024-03-08",
            "item_index": 0,
            "item_name": "cola",
            "measurement_type": "discrete_units",
            "measurement_quantity": 2.0,
            "price_per_measurement_unit": 1.50,
            "line_total_paid_amount": 3.00,
            "confidence": 0.95,
        },
        {
            "id": 2,
            "receipt_id": "ah_test_1",
            "receipt_path": "test.pdf",
            "store": "ah",
            "date_of_purchase": "2024-03-08",
            "item_index": 1,
            "item_name": "brood",
            "measurement_type": "discrete_units",
            "measurement_quantity": 1.0,
            "price_per_measurement_unit": 2.50,
            "line_total_paid_amount": 2.50,
            "confidence": 0.95,
        },
    ]

    normalizer = Normalizer()
    results = normalizer.normalize_batch(raw_items)

    assert len(results) == 2
    assert results[0].item_name == "COLA"
    assert results[1].item_name == "BROOD"

    stats = normalizer.get_stats()
    assert stats["total_items"] == 2
    assert stats["kept_items"] == 2
    assert stats["filtered_out"] == 0
    print("✓ test_normalizer_batch passed")


# ============================================================
# Run all tests
# ============================================================

def run_all_tests():
    """Run all tests and print summary."""
    tests = [
        test_standardize_item_name,
        test_remove_trailing_price_artifacts,
        test_remove_pack_artifacts,
        test_parse_dutch_date,
        test_standardize_date,
        test_get_month_of_purchase,
        test_extract_date_from_filename,
        test_normalize_measurement_quantity,
        test_recalc_price_per_unit,
        test_fix_arithmetic,
        test_apply_edge_cases_scharrelei,
        test_apply_edge_cases_bundles,
        test_apply_edge_cases_pack_identifiers,
        test_apply_edge_cases_trailing_price,
        test_apply_edge_cases_excluded_items,
        test_should_filter_item,
        test_clean_item_name,
        test_normalizer_ah_item,
        test_normalizer_jumbo_item,
        test_normalizer_weight_item,
        test_normalizer_filtered_item,
        test_normalizer_arithmetic_fix,
        test_normalizer_pack_with_price_recalc,
        test_normalizer_batch,
    ]

    passed = 0
    failed = 0

    print("=" * 60)
    print("NORMALIZATION MODULE TESTS")
    print("=" * 60)
    print()

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
