"""
Deterministic parser for Jumbo receipts using regex patterns.

Jumbo receipts have a different format from AH:
- No table columns
- Product name on left, price on right
- Quantity on separate line: "2 X 1,99" followed by total on same or next line
- Weight in product name: "Jb Soepgroente 400gr"
- Discount rows: "ACTIE PASTA&SAUZEN" with negative amount

IGNORES:
- ACTIE (discounts)
- Statiegeld (deposits)
- Totaal / Totaal korting (totals)
- Store header, date, metadata
"""

import re
from typing import List, Optional, Tuple
from v2.jumbo_pipeline.state import JumboPipelineState


# Regex patterns for Jumbo receipt lines
PATTERNS = {
    # Quantity line: "2 X 1,99" or "4X 1,99 3,98" or "4X 1,99 P 7,96" (with P indicator)
    # May have total on same line and optional "P" price-marked indicator
    "quantity_line": re.compile(
        r"^(\d+)\s*X\s*([\d]+,[\d]{2})(?:\s+P)?(?:\s+([\d]+,[\d]{2}))?\s*$",
        re.IGNORECASE
    ),

    # Price at end of line: "2,49" or "€ 28,79" or "-3,59"
    "price_at_end": re.compile(r"(-?€?\s*[\d]+,[\d]{2})\s*$"),

    # Discount row: "ACTIE PASTA&SAUZEN" or "ACTIE KLEENEX" (IGNORE)
    "discount": re.compile(r"^ACTIE\s+", re.IGNORECASE),

    # Weight in product name: "400gr", "360gr", "800g"
    "weight_in_name": re.compile(r"(\d+)\s*(?:gr|g)\b", re.IGNORECASE),

    # "P" indicator (price-marked item) - matches " P " in middle or " P" at end
    "price_marked": re.compile(r"\s+P(?:\s+|$)", re.IGNORECASE),

    # Date line (IGNORE as item): "zaterdag 24 mei 2025" or "Vrijdag 3 juli 2026"
    "date_line": re.compile(
        r"(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\s+\d{1,2}\s+"
        r"(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\s+\d{4}",
        re.IGNORECASE
    ),

    # Date with year at end (like "Zaterdag 29 augustus 2026" being parsed as price)
    "year_at_end": re.compile(r"\s+(\d{4})\s*$"),

    # Lines to IGNORE
    # Note: JUMBO is matched only as standalone logo line (^JUMBO\s*$), not as prefix
    # This allows items like "Jumbo Aardbeien" to be parsed correctly
    "ignore_lines": re.compile(
        r"^\s*("
        r"JUMBO\s*$|"                # Logo (standalone only!)
        r"JUNIBO\s*$|"               # Logo with OCR typo
        r"Jouw\s+boodschappen|"      # "Your groceries"
        r"Producten|"                # "Products" header
        r"Totaal|"                   # Total lines
        r"Korting|"                  # Discount
        r"BTW|"                      # VAT
        r"Incl|"                     # Including
        r"De\s+prijs|"               # The price
        r"Subtotaal|"                # Subtotal
        r"Transact|"                 # Transaction
        r"Datum|"                    # Date
        r"Klant|"                    # Customer
        r"Order|"                    # Order
        r"Betaald|"                  # Paid
        r"Contactless|"              # Contactless
        r"Pinnen|"                   # PIN
        r"Mastercard|"               # Mastercard
        r"Visa|"                     # Visa
        r"Te\s+betalen|"             # To pay
        r"Betaal|"                   # Pay
        r"ACTIE|"                    # Action/discount
        r"KIES\s*&|"                 # Promotion
        r"Statiegeld|"               # Deposit (IGNORE!)
        r"\+?Statiegeld|"            # Deposit with +
        r"EMBALLAGE|"                # Packaging deposit
        r"\d{1,2}:\d{2}|"            # Time (12:19)
        r"om\s+\d{1,2}:\d{2}|"       # "om 12:19"
        r"uur\s*$"                   # "uur" (hour) at end
        r")",
        re.IGNORECASE
    ),
}


def parse_price(price_str: str) -> Optional[float]:
    """Parse Dutch price format (comma as decimal separator)."""
    if not price_str:
        return None
    # Remove currency symbol and spaces
    cleaned = price_str.replace("€", "").replace(" ", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned.replace(",", "."))
    except ValueError:
        return None


def extract_weight_from_name(name: str) -> Optional[float]:
    """Extract weight in grams from product name (e.g., '400gr' -> 400)."""
    match = PATTERNS["weight_in_name"].search(name)
    if match:
        return float(match.group(1))
    return None


def is_valid_item_name(name: str) -> bool:
    """Check if a name looks like a valid product name."""
    if not name or len(name.strip()) < 2:
        return False
    # Reject if it's just numbers, prices, or symbols
    if re.match(r"^[\d\s,.\-€:]+$", name.strip()):
        return False
    # Reject if it starts with common non-item patterns
    if re.match(r"^[\[\]\+\-=*X]", name.strip()):
        return False
    # Reject date-like strings
    if PATTERNS["date_line"].search(name):
        return False
    # Reject if it's just a quantity pattern like "2 X 1,99" or "4X 1,99 P"
    if re.match(r"^\d+\s*X\s*[\d,]+(\s+P)?$", name.strip(), re.IGNORECASE):
        return False
    # Reject day names
    if re.match(r"^(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\b", name.strip(), re.IGNORECASE):
        return False
    return True


def parse_jumbo_lines(lines: List[str]) -> List[dict]:
    """
    Parse Jumbo receipt lines into grocery items only.

    Jumbo format:
        Product Name                    2,49
        Product Name 2
          2 X 1,99                      3,98
        ACTIE DISCOUNT                 -3,59  (IGNORED)

    Returns:
        List of grocery item dicts (discounts excluded)
    """
    items = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines and known headers/ignore patterns
        if not line or PATTERNS["ignore_lines"].match(line):
            i += 1
            continue

        # IGNORE date lines (they contain day names and years)
        if PATTERNS["date_line"].search(line):
            i += 1
            continue

        # IGNORE discount rows (ACTIE)
        if PATTERNS["discount"].match(line):
            # Skip this line and the next line if it has the amount
            i += 1
            if i < len(lines):
                next_line = lines[i].strip()
                # Check if next line is just a negative amount
                if re.match(r"^-?[\d,]+$", next_line) or PATTERNS["price_at_end"].search(next_line):
                    i += 1
            continue

        # IGNORE total lines
        if line.upper().startswith("TOTAAL"):
            i += 1
            continue

        # Check if this is a quantity line ("2 X 1,99" or "2 X 1,99  3,98")
        qty_match = PATTERNS["quantity_line"].match(line)
        if qty_match:
            qty = int(qty_match.group(1))
            unit_price = parse_price(qty_match.group(2))
            total = parse_price(qty_match.group(3)) if qty_match.group(3) else None

            # If total not on same line, check next line
            if total is None and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                total_match = PATTERNS["price_at_end"].search(next_line)
                if total_match:
                    total = parse_price(total_match.group(1))
                    # Only skip next line if it's just a price
                    if re.match(r"^\s*-?€?\s*[\d]+,[\d]{2}\s*$", next_line):
                        i += 1

            # Associate with previous item if it's pending quantity
            if items and items[-1].get("_pending_quantity"):
                items[-1]["measurement_quantity"] = float(qty)
                items[-1]["price_per_measurement_unit"] = unit_price
                if total:
                    items[-1]["line_total_paid_amount"] = total
                del items[-1]["_pending_quantity"]
            else:
                # Quantity line without preceding item - this is an error
                # Create a placeholder item (will be filtered later if invalid)
                pass

            i += 1
            continue

        # Check if next line is a quantity line (for multi-quantity items)
        # This handles the case where item name is on one line and "2 X 1,99" on the next
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if PATTERNS["quantity_line"].match(next_line):
                # This line is an item name with quantity on next line
                # Don't require a price on this line
                name = line.strip()
                name = PATTERNS["price_marked"].sub(" ", name).strip()
                name = re.sub(r"\s+", " ", name).strip()

                if is_valid_item_name(name):
                    # Check for weight in name
                    weight_grams = extract_weight_from_name(name)

                    if weight_grams and weight_grams > 0:
                        measurement_type = "weight_in_grams"
                        quantity = weight_grams
                    else:
                        measurement_type = "discrete_units"
                        quantity = None  # Will be set by quantity line

                    item = {
                        "item_name": name,
                        "measurement_type": measurement_type,
                        "measurement_quantity": quantity,
                        "price_per_measurement_unit": None,
                        "line_total_paid_amount": None,  # Will be set by quantity line
                        "_pending_quantity": True,
                        "_source": "deterministic",
                    }
                    items.append(item)
                    i += 1
                    continue

        # Check if line ends with a price (regular item)
        price_match = PATTERNS["price_at_end"].search(line)
        if price_match:
            price_str = price_match.group(1)
            amount = parse_price(price_str)

            # Skip zero or negative amounts (could be discounts we missed)
            if amount is None or amount <= 0:
                i += 1
                continue

            # Skip if the "price" is actually a year (like "2026" in "Zaterdag 29 augustus 2026")
            # Years are 4 digits without comma
            if re.match(r"^\d{4}$", price_str.strip()):
                i += 1
                continue

            # Extract item name (remove price and "P" indicator)
            name = line[:price_match.start()].strip()
            name = PATTERNS["price_marked"].sub(" ", name).strip()
            name = re.sub(r"\s+", " ", name).strip()

            if not is_valid_item_name(name):
                i += 1
                continue

            # Check for weight in name
            weight_grams = extract_weight_from_name(name)

            # Determine measurement type
            if weight_grams and weight_grams > 0:
                measurement_type = "weight_in_grams"
                quantity = weight_grams
            else:
                measurement_type = "discrete_units"
                quantity = 1.0

            item = {
                "item_name": name,
                "measurement_type": measurement_type,
                "measurement_quantity": quantity,
                "price_per_measurement_unit": None,
                "line_total_paid_amount": amount,
                "_pending_quantity": False,
                "_source": "deterministic",
            }

            # Check if next line is a quantity line (for multi-quantity items)
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if PATTERNS["quantity_line"].match(next_line):
                    item["_pending_quantity"] = True
                    item["measurement_type"] = "discrete_units"
                    item["measurement_quantity"] = None  # Will be set by quantity line

            items.append(item)

        i += 1

    # Post-process: fix items with pending quantity (no quantity line found)
    for item in items:
        if item.get("_pending_quantity"):
            # No quantity line found, default to 1
            item["measurement_quantity"] = 1.0
            item["measurement_type"] = "discrete_units"
            del item["_pending_quantity"]

        # Calculate unit prices for items that don't have them
        if item.get("price_per_measurement_unit") is None:
            qty = item.get("measurement_quantity")
            total = item.get("line_total_paid_amount")
            if qty and total and qty > 0:
                item["price_per_measurement_unit"] = round(total / qty, 2)

        # Clean up internal fields
        for key in list(item.keys()):
            if key.startswith("_"):
                del item[key]

    return items


def extract_date_from_text(text: str) -> Optional[str]:
    """Extract date from Jumbo receipt header."""
    for line in text.split("\n"):
        match = PATTERNS["date_line"].search(line)
        if match:
            # Clean up the line (remove time, "om", "uur", etc.)
            cleaned = line.strip()
            # Remove time patterns
            cleaned = re.sub(r",?\s*om\s+\d{1,2}:\d{2}\s*uur", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\d{1,2}:\d{2}", "", cleaned)
            return cleaned.strip()
    return None


def deterministic_parse_node(state: JumboPipelineState) -> JumboPipelineState:
    """
    LangGraph node: Parse Jumbo receipt using deterministic regex rules.

    Extracts ONLY grocery items. Ignores discounts, deposits, totals, metadata.
    """
    raw_text = state.get("raw_text", "")
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

    items = parse_jumbo_lines(lines)
    date_of_purchase = extract_date_from_text(raw_text)

    return {
        **state,
        "deterministic_items": items,
        "date_of_purchase": date_of_purchase,
        "actie_discounts": [],  # Ignored
        "processing_steps": state.get("processing_steps", []) + ["deterministic_parse"],
    }
