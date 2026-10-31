"""
Tests for the label validator.

Usage:
    python -m pytest v2/stage3b_classification_review/tests/test_validator.py -v
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[3]))

import pytest

from v2.stage3b_classification_review.validator import (
    validate_label,
    validate_label_string,
    suggest_correction,
    list_taxonomy,
    COMMON_MISTAKES,
)
from v2.stage3_classification.taxonomy import TAXONOMY, all_labels


class TestValidateLabel:
    """Test validate_label function."""
    
    def test_valid_labels(self):
        """Valid labels should pass."""
        valid_cases = [
            ("Carnes", "Jamón"),
            ("Bebidas", "Cerveza"),
            ("Lácteos", "Queso"),
            ("Frutas & Verduras", "Manzana"),
            ("Hogar", "Limpieza"),
            ("Snacks", "Papas Fritas"),
            ("Dulces", "Helado"),
        ]
        for category, subcategory in valid_cases:
            is_valid, msg = validate_label(category, subcategory)
            assert is_valid, f"{category} > {subcategory} should be valid: {msg}"
            assert msg == "Valid"
    
    def test_invalid_subcategory(self):
        """Invalid subcategories should fail."""
        invalid_cases = [
            ("Snacks", "Chips"),
            ("Bebidas", "Energy Drink"),
            ("Carnes", "Bacon"),
            ("Lácteos", "Yogur Griego"),
        ]
        for category, subcategory in invalid_cases:
            is_valid, msg = validate_label(category, subcategory)
            assert not is_valid, f"{category} > {subcategory} should be invalid"
            assert "Invalid subcategory" in msg
    
    def test_invalid_category(self):
        """Invalid categories should fail."""
        is_valid, msg = validate_label("InvalidCategory", "Something")
        assert not is_valid
        assert "Invalid category" in msg
    
    def test_otros_always_valid(self):
        """Otros should be valid for every category."""
        for category in TAXONOMY.keys():
            is_valid, msg = validate_label(category, "Otros")
            assert is_valid, f"{category} > Otros should be valid"


class TestSuggestCorrection:
    """Test suggest_correction function."""
    
    def test_valid_label_unchanged(self):
        """Valid labels should be returned unchanged."""
        result = suggest_correction("Carnes", "Jamón")
        assert result == "Carnes > Jamón"
    
    def test_common_mistakes(self):
        """Common mistakes should be corrected."""
        cases = [
            ("Snacks", "Chips", "Snacks > Papas Fritas"),
            ("Snacks", "Crisps", "Snacks > Papas Fritas"),
            ("Bebidas", "Soda", "Bebidas > Refresco"),
            ("Bebidas", "Energy Drink", "Bebidas > Refresco"),
            ("Carnes", "Chicken", "Carnes > Pollo"),
            ("Carnes", "Bacon", "Carnes > Cerdo"),
            ("Dulces", "Ice Cream", "Dulces > Helado"),
            ("Lácteos", "Cheese", "Lácteos > Queso"),
            ("Frutas & Verduras", "Apple", "Frutas & Verduras > Manzana"),
        ]
        for category, subcategory, expected in cases:
            result = suggest_correction(category, subcategory)
            assert result == expected, f"{category} > {subcategory} should correct to {expected}, got {result}"
    
    def test_unknown_subcategory_gets_otros(self):
        """Unknown subcategories should get Otros."""
        result = suggest_correction("Snacks", "SomethingWeird")
        assert result == "Snacks > Otros"
    
    def test_invalid_category(self):
        """Invalid categories should return NEEDS TAXONOMY UPDATE."""
        result = suggest_correction("InvalidCategory", "Something")
        assert "NEEDS TAXONOMY UPDATE" in result


class TestValidateLabelString:
    """Test validate_label_string function."""
    
    def test_valid_string(self):
        """Valid strings should pass."""
        is_valid, msg, corrected = validate_label_string("Carnes > Jamón")
        assert is_valid
        assert corrected == "Carnes > Jamón"
    
    def test_invalid_string(self):
        """Invalid strings should fail with correction."""
        is_valid, msg, corrected = validate_label_string("Snacks > Chips")
        assert not is_valid
        assert corrected == "Snacks > Papas Fritas"
    
    def test_needs_taxonomy_update(self):
        """NEEDS TAXONOMY UPDATE should be treated as valid."""
        is_valid, msg, corrected = validate_label_string("NEEDS TAXONOMY UPDATE: Snacks > Chips")
        assert is_valid
        assert "taxonomy update" in msg.lower()
    
    def test_keep_marker(self):
        """Keep markers should be treated as valid."""
        for marker in ["keep", "(keep)", "no change", "correct", "n/a"]:
            is_valid, msg, corrected = validate_label_string(marker)
            assert is_valid, f"'{marker}' should be valid"
    
    def test_unparseable(self):
        """Unparseable strings should fail."""
        is_valid, msg, corrected = validate_label_string("just some text")
        assert not is_valid
        assert "Could not parse" in msg


class TestCommonMistakes:
    """Test COMMON_MISTAKES mapping."""
    
    def test_all_corrections_are_valid(self):
        """All COMMON_MISTAKES corrections should be valid taxonomy pairs."""
        for wrong, (category, subcategory) in COMMON_MISTAKES.items():
            is_valid, msg = validate_label(category, subcategory)
            assert is_valid, f"COMMON_MISTAKES['{wrong}'] = {category} > {subcategory} is not valid: {msg}"
    
    def test_has_common_english_terms(self):
        """Should have common English terms."""
        common_terms = ["chips", "soda", "chicken", "cheese", "apple", "bread", "milk"]
        for term in common_terms:
            assert term in COMMON_MISTAKES, f"Missing common term: {term}"


class TestTaxonomy:
    """Test taxonomy integrity."""
    
    def test_total_pairs(self):
        """Should have 127 valid pairs."""
        labels = all_labels()
        assert len(labels) == 127
    
    def test_all_categories_have_otros(self):
        """Every category should have Otros."""
        for category, subcategories in TAXONOMY.items():
            assert "Otros" in subcategories, f"{category} missing Otros"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
