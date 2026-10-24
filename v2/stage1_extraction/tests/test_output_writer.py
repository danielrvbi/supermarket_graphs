"""
Unit tests for Stage 1 output writer (non-product filtering).

Usage:
    python -m pytest v2/stage1_extraction/tests/test_output_writer.py -v
"""

import json
import sys
import tempfile
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parents[3]))

from v2.stage1_extraction.output_writer import OutputWriter
from v2.stage1_extraction.store import ProcessedDataStore


def test_write_receipt_filters_non_products_from_db(tmp_path):
    """Non-product lines are kept in JSON but excluded from the database."""
    # Use a temporary processed directory
    processed_dir = tmp_path / "processed"

    writer = OutputWriter(processed_dir=str(processed_dir))

    receipt_data = {
        "date_of_purchase": "2025-02-22",
        "items": [
            {"item_name": "COLA ZERO", "measurement_type": "discrete_units",
             "measurement_quantity": 1.0, "price_per_measurement_unit": 1.79,
             "line_total_paid_amount": 1.79},
            {"item_name": "KOOPZEGELS", "measurement_type": "discrete_units",
             "measurement_quantity": 1.0, "price_per_measurement_unit": 0.10,
             "line_total_paid_amount": 0.10},
            {"item_name": "AH BIO KIPFI", "measurement_type": "discrete_units",
             "measurement_quantity": 2.0, "price_per_measurement_unit": 3.50,
             "line_total_paid_amount": 7.00},
            {"item_name": "STATIEGELD FLES", "measurement_type": "discrete_units",
             "measurement_quantity": 1.0, "price_per_measurement_unit": 0.25,
             "line_total_paid_amount": 0.25},
        ],
    }

    writer.write_receipt(
        store="ah",
        receipt_path="raw_receipts/ah/test_receipt.pdf",
        receipt_data=receipt_data,
        status="clean",
        metadata={"confidence": 0.95},
    )

    # Check JSON file keeps ALL items (historical record)
    json_files = list((processed_dir / "clean" / "ah").glob("*.json"))
    assert len(json_files) == 1
    json_data = json.loads(json_files[0].read_text())
    json_item_names = {item["item_name"] for item in json_data["items"]}
    assert json_item_names == {"COLA ZERO", "KOOPZEGELS", "AH BIO KIPFI", "STATIEGELD FLES"}

    # Check database only has real products
    db = ProcessedDataStore(str(processed_dir / "processed_data.db"))
    db_items = db.query_items(limit=100)
    db_item_names = {item["item_name"] for item in db_items}
    assert db_item_names == {"COLA ZERO", "AH BIO KIPFI"}
    assert "KOOPZEGELS" not in db_item_names
    assert "STATIEGELD FLES" not in db_item_names


def test_write_receipt_all_products_no_filtering(tmp_path):
    """Receipts with only real products are written normally."""
    processed_dir = tmp_path / "processed"
    writer = OutputWriter(processed_dir=str(processed_dir))

    receipt_data = {
        "date_of_purchase": "2025-01-15",
        "items": [
            {"item_name": "COLA ZERO", "measurement_type": "discrete_units",
             "measurement_quantity": 2.0, "price_per_measurement_unit": 1.79,
             "line_total_paid_amount": 3.58},
            {"item_name": "BROOD", "measurement_type": "discrete_units",
             "measurement_quantity": 1.0, "price_per_measurement_unit": 2.49,
             "line_total_paid_amount": 2.49},
        ],
    }

    writer.write_receipt(
        store="ah",
        receipt_path="raw_receipts/ah/test_receipt2.pdf",
        receipt_data=receipt_data,
        status="clean",
        metadata={"confidence": 0.99},
    )

    db = ProcessedDataStore(str(processed_dir / "processed_data.db"))
    db_items = db.query_items(limit=100)
    assert len(db_items) == 2
    db_item_names = {item["item_name"] for item in db_items}
    assert db_item_names == {"COLA ZERO", "BROOD"}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        test_write_receipt_filters_non_products_from_db(Path(tmp))
        print("✓ test_write_receipt_filters_non_products_from_db passed")

    with tempfile.TemporaryDirectory() as tmp:
        test_write_receipt_all_products_no_filtering(Path(tmp))
        print("✓ test_write_receipt_all_products_no_filtering passed")

    print("All output_writer tests passed!")
