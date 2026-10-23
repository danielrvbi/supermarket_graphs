"""
Deterministic parser for AH receipts using regex patterns.

Parses the AH table format (space-aligned columns, not pipe-separated):
  AANTAL       OMSCHRIJVING               PRIJS  BEDRAG
  2            GI TOSCANA                  4,25     8,50 B
  1            SNOEP TOMAAT                         1,99
  0.598KG      CHIQUITA LOS                2,29     1,37

IGNORES:
- BONUSKAART (loyalty card)
- +STATIEGELD (deposits)
- BONUS / UW VOORDEEL (discounts)
- SUBTOTAAL / TOTAAL (totals)
- BTW / 9% / 21% (taxes)
- All metadata, payment info, terminal info
"""

import re
from typing import List, Optional
from v2.ah_pipeline.state import AHPipelineState


# Regex patterns for AH receipt lines (space-aligned format)
PATTERNS = {
    # Weight item: "0.598KG CHIQUITA LOS  2,29 1,37"
    "weight_item": re.compile(
        r"^\s*(\d+\.\d+)\s*KG\s+(.+?)\s+([\d]+,[\d]{2})\s+([\d]+,[\d]{2})\s*([A-Z])?\s*$",
        re.IGNORECASE
    ),

    # Regular item with unit price AND total: "2  GI TOSCANA  4,25  8,50 B"
    "item_two_prices": re.compile(
        r"^\s*(\d+)\s+(.+?)\s+([\d]+,[\d]{2})\s+([\d]+,[\d]{2})\s*([A-Z])?\s*$"
    ),

    # Regular item with only total (no unit price): "1  SNOEP TOMAAT  1,99"
    # May have optional VAT indicator suffix: "1  COCA-COLA  5,09 B"
    "item_one_price": re.compile(
        r"^\s*(\d+)\s+(.+?)\s{2,}([\d]+,[\d]{2})\s*([A-Z])?\s*$"
    ),

    # Rows to IGNORE (never extract as items)
    # Note: Some rows have a quantity prefix (e.g., "9  SUBTOTAAL  23,28")
    "ignore_rows": re.compile(
        r"^\s*(\d+\s+)?("  # Optional quantity prefix
        r"BONUSKAART|"           # Loyalty card
        r"\+?STATIEGELD|"       # Deposits
        r"BONUS|"                # Bonus discounts
        r"UW\s+VOORDEEL|"        # Savings
        r"Waarvan|"              # "Of which"
        r"BONUS\s+BOX|"          # Bonus box
        r"SUBTOTAAL|"            # Subtotal
        r"TOTAAL|"               # Total
        r"SPAARACTIES|"          # Savings actions
        r"eSPAARZEGEL|"          # Savings stamp
        r"KOOPZEGELS|"           # Purchase stamps
        r"EMBALLAGE|"            # Packaging deposit
        r"BETAALD\s+MET|"        # Paid with
        r"PINNEN|"               # PIN payment
        r"CONTROLE|"             # Control section
        r"TEKORT|"               # Shortage
        r"TEVEEL|"               # Excess
        r"BTW|"                  # VAT
        r"9%|"                   # 9% VAT
        r"21%|"                  # 21% VAT
        r"Kopie|"                # Copy
        r"Kaarthouder|"          # Cardholder
        r"Terminal|"             # Terminal
        r"Merchant|"             # Merchant
        r"Period|"               # Period
        r"Token|"                # Token
        r"Transactie|"           # Transaction
        r"Contact|"              # Contactless
        r"Kaart|"                # Card
        r"Datum|"                # Date
        r"Auth|"                 # Authorization
        r"Modo|"                 # Mode
        r"Tarjeta|"              # Card (Spanish)
        r"Numero|"               # Number
        r"Fecha|"                # Date (Spanish)
        r"Código|"               # Code
        r"POI|"                  # POI
        r"CLIENT|"               # Client
        r"RECORD|"               # Record
        r"Comerciante|"          # Merchant (Spanish)
        r"Operacion|"            # Operation
        r"PAGO|"                 # Payment
        r"AKKOORD|"              # OK
        r"Albert\s+Heijn|"       # Store name
        r"Amsterdam|"            # City
        r"www\.ah|"              # Website
        r"Vragen|"               # Questions
        r"servicemedewerkers|"   # Service staff
        r"helpen|"               # Help
        r"kassabon|"             # Receipt
        r"\["                    # Literal [ character
        r")",
        re.IGNORECASE
    ),

    # Subtotal: "9  SUBTOTAAL  23,28" (for metadata only, not extracted)
    "subtotal": re.compile(
        r"^\s*\d+\s+SUBTOTAAL\s+([\d]+,[\d]{2})",
        re.IGNORECASE
    ),

    # Total (for metadata only): "TOTAAL  19,03"
    "total": re.compile(
        r"^\s*TOTAAL\s+([\d]+,[\d]{2})\s*$",
        re.IGNORECASE
    ),

    # Date at bottom: "16:21 08-03-2024" or "13:20  22-10-2026"
    "date_footer": re.compile(r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"),
}


def parse_price(price_str: str) -> Optional[float]:
    """Parse Dutch price format (comma as decimal separator)."""
    if not price_str or price_str.strip() == "":
        return None
    try:
        return float(price_str.replace(",", ".").strip())
    except ValueError:
        return None


def parse_ah_line(line: str) -> Optional[dict]:
    """
    Parse a single line from an AH receipt.

    Returns:
        Item dict if the line is a valid grocery item, None otherwise
    """
    line = line.rstrip()
    stripped = line.strip()

    if not stripped:
        return None

    # IGNORE all non-item rows (deposits, discounts, taxes, totals, metadata)
    if PATTERNS["ignore_rows"].match(stripped):
        return None

    # Skip lines that are just numbers or just whitespace
    if re.match(r"^[\d\s,.\-:]+$", stripped):
        return None

    # Skip lines that start with common non-item patterns
    if re.match(r"^[\[\]\+\-=*]+", stripped):
        return None

    # Try weight item pattern first: "0.598KG CHIQUITA LOS  2,29 1,37"
    match = PATTERNS["weight_item"].match(line)
    if match:
        kg_str, name, price_per_kg_str, total_str, vat = match.groups()
        kg = float(kg_str)
        name = name.strip()

        # Skip if name looks like a non-item
        if not name or len(name) < 2:
            return None

        return {
            "item_name": name,
            "measurement_type": "weight_in_grams",
            "measurement_quantity": kg * 1000,  # Convert to grams
            "price_per_measurement_unit": parse_price(price_per_kg_str),  # Price per kg
            "line_total_paid_amount": parse_price(total_str),
            "_source": "deterministic",
        }

    # Try regular item with two prices (unit + total): "2  GI TOSCANA  4,25  8,50 B"
    match = PATTERNS["item_two_prices"].match(line)
    if match:
        qty_str, name, price_str, total_str, vat = match.groups()
        qty = int(qty_str)
        name = name.strip()

        if not name or len(name) < 2:
            return None

        unit_price = parse_price(price_str)
        total = parse_price(total_str)

        return {
            "item_name": name,
            "measurement_type": "discrete_units",
            "measurement_quantity": float(qty),
            "price_per_measurement_unit": unit_price,
            "line_total_paid_amount": total,
            "_source": "deterministic",
        }

    # Try regular item with one price (total only): "1  SNOEP TOMAAT  1,99" or "1  COCA-COLA  5,09 B"
    match = PATTERNS["item_one_price"].match(line)
    if match:
        qty_str, name, total_str, vat = match.groups()
        qty = int(qty_str)
        name = name.strip()

        if not name or len(name) < 2:
            return None

        total = parse_price(total_str)
        # Calculate unit price if not visible
        unit_price = round(total / qty, 2) if qty > 0 else None

        return {
            "item_name": name,
            "measurement_type": "discrete_units",
            "measurement_quantity": float(qty),
            "price_per_measurement_unit": unit_price,
            "line_total_paid_amount": total,
            "_source": "deterministic",
        }

    return None


def extract_date_from_text(text: str) -> Optional[str]:
    """Extract date from receipt footer."""
    for line in text.split("\n"):
        match = PATTERNS["date_footer"].search(line)
        if match:
            date_str = match.group(1)
            if re.match(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$", date_str):
                # Normalize to YYYY-MM-DD
                parts = re.split(r"[-/]", date_str)
                if len(parts) == 3:
                    day, month, year = parts
                    if len(year) == 2:
                        year = "20" + year
                    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None


def extract_total_from_text(text: str) -> Optional[float]:
    """Extract TOTAAL from receipt (for metadata only, not validation)."""
    for line in text.split("\n"):
        if "SUBTOTAAL" in line.upper() or "BTW" in line.upper():
            continue
        match = PATTERNS["total"].match(line)
        if match:
            return parse_price(match.group(1))
    return None


def deterministic_parse_node(state: AHPipelineState) -> AHPipelineState:
    """
    LangGraph node: Parse AH receipt using deterministic regex rules.

    Extracts ONLY grocery items. Ignores deposits, discounts, taxes, totals.
    """
    raw_text = state.get("raw_text", "")
    lines = raw_text.split("\n")

    items = []

    for line in lines:
        item = parse_ah_line(line)
        if item:
            items.append(item)

    # Safety net: filter out any items that slipped through with non-item names
    non_item_keywords = [
        "SUBTOTAAL", "TOTAAL", "BONUSKAART", "STATIEGELD", "BONUS",
        "VOORDEEL", "BTW", "SPAAR", "KOOPZEGEL", "EMBALLAGE",
        "PINNEN", "BETAALD", "CONTROLE", "TEKORT", "TEVEEL"
    ]
    items = [
        item for item in items
        if not any(kw in item.get("item_name", "").upper() for kw in non_item_keywords)
    ]

    # Extract date from text or filename
    date_from_text = extract_date_from_text(raw_text)
    date_of_purchase = date_from_text or state.get("date_from_filename")
    if date_of_purchase and "-" in date_of_purchase:
        # Convert YYYY-MM-DD to YYYY/MM/DD for v1 compatibility
        date_of_purchase = date_of_purchase.replace("-", "/")

    # Extract total for metadata only (NOT used for validation)
    total = extract_total_from_text(raw_text)

    return {
        **state,
        "deterministic_items": items,
        "date_of_purchase": date_of_purchase,
        "total": total,  # Metadata only
        "statiegeld_items": [],  # Ignored
        "bonus_discounts": [],   # Ignored
        "processing_steps": state.get("processing_steps", []) + ["deterministic_parse"],
    }
