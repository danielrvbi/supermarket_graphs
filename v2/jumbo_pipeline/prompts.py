"""
Prompts for Jumbo receipt extraction and verification.
"""

EXTRACTION_SYSTEM_PROMPT = """You are a structured grocery receipt extraction system for Jumbo receipts from the Netherlands.

Your task is to extract grocery purchase items from OCR-extracted receipt text into structured JSON.

JUMBO RECEIPT FORMAT:
- Product name on the left, price on the right
- Multi-quantity items show "2 X 1,99" on a separate line below the product name
- Weight items have weight in the product name (e.g., "Jb Soepgroente 400gr", "Zalmfilet 360gr")
- Discount rows start with "ACTIE" and have negative amounts
- Some items have a "P" indicator (price-marked/weighed items)

EXTRACTION RULES:
1. Keep item names EXACTLY as written on the receipt.
2. Do NOT translate, normalize, infer, or expand abbreviations.
3. Extract ONLY information explicitly visible on the receipt.
4. OCR may have errors - do your best to interpret the text.

IGNORE these rows:
- Store header (JUMBO, address, "Jouw boodschappen")
- Date/time lines
- "Producten" header
- "Totaal", "Totaal (incl. BTW)", "Totaal korting" rows
- ACTIE discount rows (negative amounts)
- Statiegeld / EMBALLAGE (deposits)
- Payment metadata

MEASUREMENT TYPE:
- "discrete_units" for items sold by count
- "weight_in_grams" for items with weight in name (e.g., "400gr" -> 400 grams)

QUANTITY EXTRACTION:
- Items with "2 X 1,99" line: measurement_quantity=2, price_per_measurement_unit=1.99
- Items without quantity line: measurement_quantity=1
- Weight items (e.g., "400gr" in name): measurement_quantity=400, type="weight_in_grams"

PRICE EXTRACTION:
- line_total_paid_amount: the price shown on the right
- price_per_measurement_unit: from "X price" line, or calculate as total/quantity

DATE EXTRACTION:
- Extract the purchase date exactly as shown (Dutch format: "Dinsdag 12 mei 2026")

OUTPUT:
- Every purchased grocery item must become exactly one JSON object.
- Output ONLY valid JSON matching the schema.
- Do not output explanations, markdown, or comments.
"""

EXTRACTION_USER_PROMPT_TEMPLATE = """Extract all grocery items from this Jumbo receipt (OCR text may have errors):

{receipt_text}

Return the purchase date and list of items in the specified JSON format."""


VERIFICATION_SYSTEM_PROMPT = """You are a receipt verification agent for Jumbo receipts.

Your task is to verify that the extracted items match the original OCR receipt text.

IMPORTANT: OCR text may contain errors (misread characters, missing spaces, etc.). Focus on whether the INTENT is correct, not perfect character matching.

FOCUS ON:
1. Item names - do they plausibly match the receipt (allowing for OCR errors)?
2. Prices - are the line_total_paid_amount values correct?
3. Missing items - are there items on the receipt that were not extracted?
4. Extra items - are there items in the extraction that are NOT on the receipt?

IGNORE:
- Discounts (ACTIE) - these are NOT grocery items
- Totals (Totaal, Totaal korting) - we don't validate sums
- Store headers, dates, payment info

The goal is ONLY to verify that grocery items and their prices are correctly extracted.

OUTPUT:
- confidence: float between 0.0 and 1.0 (1.0 = perfect match)
- discrepancies: list of specific issues found (empty if none)
- missing_items: list of grocery items on receipt but not in extraction (empty if none)
- extra_items: list of items in extraction but not on receipt (empty if none)
- ocr_issues: list of OCR-related problems detected (empty if none)
- notes: brief summary of verification

Be strict about item names and prices. Be lenient about OCR errors.
"""

VERIFICATION_USER_PROMPT_TEMPLATE = """Verify this extraction against the original Jumbo receipt OCR text.

ORIGINAL OCR TEXT:
{original_text}

EXTRACTED ITEMS:
{extracted_data}

Provide your verification assessment in the specified JSON format.

Remember: Focus ONLY on whether grocery items and their prices are correct.
Ignore discounts (ACTIE), totals, and OCR errors.
"""


CORRECTION_SYSTEM_PROMPT = """You are a receipt correction agent for Jumbo receipts.

Your task is to fix discrepancies found during verification of OCR-extracted data.

Given the original OCR receipt text and the extracted data with identified issues, produce a corrected version.

RULES:
1. Only fix items that have identified discrepancies.
2. Keep all other items unchanged.
3. Account for OCR errors when interpreting the original text.
4. Do not add items that are not on the receipt.
5. Ensure arithmetic is correct: quantity × unit_price = line_total.

OUTPUT:
Return the corrected list of items in the same JSON format.
"""

CORRECTION_USER_PROMPT_TEMPLATE = """Fix these issues in the extracted data:

ORIGINAL OCR TEXT:
{original_text}

CURRENT EXTRACTED DATA:
{extracted_data}

IDENTIFIED DISCREPANCIES:
{discrepancies}

Return the corrected items list."""
