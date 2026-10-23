"""
Main normalization orchestrator.

Ties together all normalization rules to process a single item
from the processed_data table into a normalized item for
the normalized_data table.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from v2.stage2_normalization.rules.name_standardizer import standardize_item_name
from v2.stage2_normalization.rules.date_parser import (
    standardize_date,
    get_month_of_purchase,
    extract_date_from_filename,
)
from v2.stage2_normalization.rules.unit_normalizer import normalize_measurement_quantity
from v2.stage2_normalization.rules.arithmetic_fixer import (
    fix_arithmetic,
    recalc_price_per_unit,
)
from v2.stage2_normalization.rules.item_cleaner import (
    apply_edge_cases,
    should_filter_item,
)


@dataclass
class NormalizedItem:
    """Result of normalizing a single item."""

    # Source reference
    source_id: Optional[int] = None
    receipt_id: Optional[str] = None
    store: Optional[str] = None

    # Normalized fields
    item_name: str = ""
    measurement_type: str = "discrete_units"
    measurement_quantity: Optional[float] = None
    price_per_measurement_unit: Optional[float] = None
    line_total_paid_amount: Optional[float] = None

    # Dates
    date_of_purchase: Optional[str] = None
    month_of_purchase: Optional[str] = None

    # Metadata
    normalization_rules: List[str] = field(default_factory=list)
    filtered_out: bool = False
    filter_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for database insertion."""
        return {
            "source_id": self.source_id,
            "receipt_id": self.receipt_id,
            "store": self.store,
            "item_name": self.item_name,
            "measurement_type": self.measurement_type,
            "measurement_quantity": self.measurement_quantity,
            "price_per_measurement_unit": self.price_per_measurement_unit,
            "line_total_paid_amount": self.line_total_paid_amount,
            "date_of_purchase": self.date_of_purchase,
            "month_of_purchase": self.month_of_purchase,
            "normalization_rules": self.normalization_rules,
            "filtered_out": self.filtered_out,
            "filter_reason": self.filter_reason,
        }


class Normalizer:
    """
    Orchestrates normalization of items from processed_data to normalized_data.

    Usage:
        normalizer = Normalizer()
        result = normalizer.normalize_item(raw_item_dict)
    """

    def __init__(self):
        self.stats = {
            "total_items": 0,
            "filtered_out": 0,
            "rules_applied": {},
        }

    def normalize_item(self, raw_item: Dict) -> NormalizedItem:
        """
        Normalize a single item from processed_data.

        Args:
            raw_item: Dictionary with keys from processed_data table:
                - id, receipt_id, receipt_path, store
                - date_of_purchase, item_index
                - item_name, measurement_type, measurement_quantity
                - price_per_measurement_unit, line_total_paid_amount
                - confidence

        Returns:
            NormalizedItem with cleaned and standardized values
        """
        self.stats["total_items"] += 1

        result = NormalizedItem()
        result.source_id = raw_item.get("id")
        result.receipt_id = raw_item.get("receipt_id")
        result.store = raw_item.get("store", "unknown")

        rules: List[str] = []

        # ============================================================
        # 1. Standardize item name
        # ============================================================
        raw_name = raw_item.get("item_name", "")
        item_name = standardize_item_name(raw_name)
        rules.append("name_uppercase")

        # ============================================================
        # 2. Parse and standardize dates
        # ============================================================
        raw_date = raw_item.get("date_of_purchase")
        store = result.store

        # For AH, try to extract date from filename if date is missing
        if store == "ah" and not raw_date:
            raw_date = extract_date_from_filename(raw_item.get("receipt_path", ""))

        date_iso = standardize_date(raw_date, store=store)
        if date_iso:
            rules.append("date_standardized")
            if store == "jumbo" and raw_date and raw_date != date_iso:
                rules.append("date_parse_dutch")

        result.date_of_purchase = date_iso
        result.month_of_purchase = get_month_of_purchase(date_iso)
        if result.month_of_purchase:
            rules.append("month_derived")

        # ============================================================
        # 3. Normalize measurement quantity (g → kg for weights)
        # ============================================================
        measurement_type = raw_item.get("measurement_type", "discrete_units")
        result.measurement_type = measurement_type

        raw_qty = raw_item.get("measurement_quantity")
        qty = normalize_measurement_quantity(raw_qty, measurement_type)
        if measurement_type == "weight_in_grams" and raw_qty and qty != raw_qty:
            rules.append("weight_to_kg")
        result.measurement_quantity = qty

        # ============================================================
        # 4. Get price fields
        # ============================================================
        raw_ppu = raw_item.get("price_per_measurement_unit")
        raw_total = raw_item.get("line_total_paid_amount")
        ppu = float(raw_ppu) if raw_ppu is not None else None
        total = float(raw_total) if raw_total is not None else None

        # ============================================================
        # 4b. Jumbo-specific: recalculate ppu after weight conversion
        # ============================================================
        # Ported from V1 Jumbo processing:
        #   price_per_measurement_unit = lambda df: df["line_total_paid_amount"].div(df["measurement_quantity"])
        # This is CRITICAL for weight items: after converting qty from g to kg,
        # the original ppu (per gram) needs to be recalculated as per kg.
        # Example: "KIPBLOKJES 600GR", qty=600g → 0.6kg, ppu=€0.01/g → should be €14.82/kg
        if store == "jumbo" and total is not None and qty is not None and qty != 0:
            new_ppu = recalc_price_per_unit(total, qty)
            if ppu is None or abs(new_ppu - ppu) > 0.001:
                ppu = new_ppu
                rules.append("price_recalc_jumbo")

        # ============================================================
        # 5. Fix arithmetic inconsistencies (BEFORE edge case cleaning)
        # ============================================================
        # Ported from V1: AH arithmetic fixes happen BEFORE clean_receipt_data()
        # This is important because edge case cleaning may change qty (e.g., pack identifiers)
        # and we want to fix arithmetic based on the ORIGINAL quantity
        fixed_qty, fixed_ppu, fixed_total, arith_rules = fix_arithmetic(
            quantity=qty,
            price_per_unit=ppu,
            line_total=total,
            measurement_type=measurement_type,
        )
        if fixed_qty != qty or fixed_ppu != ppu or fixed_total != total:
            qty = fixed_qty
            ppu = fixed_ppu
            total = fixed_total
        rules.extend(arith_rules)

        # ============================================================
        # 6. Apply edge case cleaning (may modify name, qty)
        # ============================================================
        # Ported from V1: clean_receipt_data() happens AFTER arithmetic fixes
        # but BEFORE the final price recalculation
        if item_name and total is not None:
            cleaned_name, new_qty, new_ppu, edge_rules = apply_edge_cases(
                item_name=item_name,
                line_total_paid_amount=total,
                measurement_quantity=qty,
                measurement_type=measurement_type,
            )
            if cleaned_name != item_name:
                item_name = cleaned_name
            if new_qty is not None and new_qty != qty:
                qty = new_qty
            if new_ppu is not None:
                ppu = new_ppu
            rules.extend(edge_rules)

        # ============================================================
        # 7. Recalculate price_per_unit if missing (Jumbo case)
        # ============================================================
        if ppu is None and total is not None and qty is not None and qty != 0:
            ppu = recalc_price_per_unit(total, qty)
            rules.append("price_recalc")

        # ============================================================
        # 8. Final recalculation: ppu = total / qty (ALWAYS, ported from V1)
        # ============================================================
        # V1 does this unconditionally at the end:
        #   .assign(price_per_measurement_unit = lambda df: df["line_total_paid_amount"].div(df["measurement_quantity"]))
        # This is CRITICAL after pack cleaning (e.g., "HEINEKEN 12P" → qty=12)
        # because the original ppu was per-pack, but after extracting qty=12,
        # we need ppu per individual unit: ppu = total / qty
        if total is not None and qty is not None and qty != 0:
            new_ppu = recalc_price_per_unit(total, qty)
            if ppu is None or abs(new_ppu - ppu) > 0.001:
                ppu = new_ppu
                rules.append("price_recalc_final")

        # ============================================================
        # 9. Round values to 3 decimals
        # ============================================================
        if qty is not None:
            qty = round(qty, 3)
        if ppu is not None:
            ppu = round(ppu, 3)
        if total is not None:
            total = round(total, 3)
            rules.append("round_values")

        # ============================================================
        # 10. Check if item should be filtered out
        # ============================================================
        if should_filter_item(item_name):
            result.filtered_out = True
            result.filter_reason = "contains_STATI"
            rules.append("filter_stati")
            self.stats["filtered_out"] += 1
            # Still return the item but mark as filtered
            # The caller will decide whether to insert it

        # ============================================================
        # Set final values
        # ============================================================
        result.item_name = item_name
        result.measurement_quantity = qty
        result.price_per_measurement_unit = ppu
        result.line_total_paid_amount = total
        result.normalization_rules = rules

        # Update stats
        for rule in rules:
            self.stats["rules_applied"][rule] = self.stats["rules_applied"].get(rule, 0) + 1

        return result

    def normalize_batch(self, raw_items: List[Dict]) -> List[NormalizedItem]:
        """
        Normalize a batch of items.

        Args:
            raw_items: List of raw item dictionaries

        Returns:
            List of NormalizedItem results
        """
        results = []
        for raw_item in raw_items:
            result = self.normalize_item(raw_item)
            results.append(result)
        return results

    def get_stats(self) -> Dict:
        """Get normalization statistics."""
        return {
            **self.stats,
            "kept_items": self.stats["total_items"] - self.stats["filtered_out"],
        }


def normalize_item(raw_item: Dict) -> NormalizedItem:
    """
    Convenience function to normalize a single item.

    Args:
        raw_item: Raw item dictionary from processed_data

    Returns:
        NormalizedItem result
    """
    normalizer = Normalizer()
    return normalizer.normalize_item(raw_item)
