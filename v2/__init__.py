"""
V2 Supermarket Receipt Pipeline

Organised in stages, each in its own folder (like v1's step1..step4 scripts):
    stage1_extraction      raw receipts    -> processed_data
    stage2_normalization   processed_data  -> normalized_data
    stage3_classification  normalized_data -> classified_data (planned)

Stages hand off through tables in processed/processed_data.db.
"""

__version__ = "2.0.0"
