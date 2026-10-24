# Classification Audit Handoff

## Purpose

Audit the v2 product classification by having Explore subagents review batches of
50 items at a time. For each item, compare against similar products (neighbours),
price, store, and quantity to identify wrong classifications.

**Output:** A simple table of flagged items with comments. No JSON files, no
complex exports. Just SQL queries and a markdown table of findings.

---

## Current State

| Metric | Value |
|--------|-------|
| Total products (`item_labels`) | 1,067 |
| Products with purchases (`normalized_data`) | 1,026 |
| Legacy labels without purchases | 41 |
| Total purchase rows | 3,751 |
| Categories | 11 (Bebidas, Carnes, Dulces, Frutas & Verduras, Higiene, Hogar, Lácteos, Panadería, Pasta/Sopas, Salud, Snacks) |

**Audit scope:** 1,067 unique items = **22 batches** (21×50 + 17)

---

## Read-Only Safeguards

1. Open database with `sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)`
2. Set `PRAGMA query_only=ON`
3. **No writes:** No `classify`, `normalize`, `review-labels set`, no DELETE/UPDATE/INSERT
4. **No API calls:** No Tavily, no embeddings, no LLM calls from the pipeline
5. **No JSON file reading:** Only SQL queries against the database
6. Workers return findings as text/markdown; parent saves to `processed/audits/<timestamp>/`

---

## ⚠️ FROZEN TAXONOMY — DO NOT INVENT SUB-CATEGORIES

**CRITICAL RULE:** The taxonomy is **FROZEN**. You may ONLY suggest categories and
sub-categories from the list below. **NEVER invent new sub-categories.**

If an item seems like it needs a sub-category that doesn't exist, use `Otros`
for that category, or mark it as `NEEDS TAXONOMY UPDATE` in your output.

### Valid Categories and Sub-Categories (127 total)

| Category | Valid Sub-Categories |
|----------|---------------------|
| **Bebidas** | Agua, Café, Cerveza, Chocolate, Cóctel, Jugo, Refresco, Té, Vino, **Otros** |
| **Carnes** | Atún, Carne Molida, Cerdo, Embutidos, Jamón, Pescado, Pollo, Res, Vegetariana, **Otros** |
| **Dulces** | Barritas, Chocolate, Galletas, Golosinas, Helado, Pasteles, Postres, Untables, **Otros** |
| **Frutas & Verduras** | Ajo, Brócoli, Brotes, Calabacín, Cebolla, Champiñones, Conservas, Ejotes, Espinaca, Frambuesa, Fresa, Fruta Seca, Frutas, Hierbas Frescas, Lechuga, Limón, Maíz, Mandarina, Mango, Manzana, Mezcla de Verduras, Naranja, Papas, Pepino, Pera, Pimiento, Plátano, Sandía, Tomate, Uvas, Verduras, Zanahoria, **Otros** |
| **Higiene** | Afeitado, Algodón, Cuidado del Cabello, Dental, Higiene Femenina, Jabón, Pañuelos, Papel Higiénico, Toallitas, **Otros** |
| **Hogar** | Aceite y Vinagre, Ambientador, Baterías, Bolsas, Cereal, Condimentos, Conservas, Decoración, Desechables, Frijoles, Harina, Jardinería, Lavandería, Limpieza, Mascotas, Mermeladas, Papelería, Salsas, Utensilios de Cocina, **Otros** |
| **Lácteos** | Crema, Huevos, Leche, Leche Deslactosada, Leche Vegetal, Mantequilla, Queso, Yogur, **Otros** |
| **Panadería** | Focaccia, Pan, Pan Dulce, Pan Hamburguesa, Pan para Hotdog, Repostería, Tortilla, **Otros** |
| **Pasta/Sopas** | Arroz, Fideos Instantáneos, Granos, Pasta, Pasta Preparada, Pasta Rellena, Sopas, **Otros** |
| **Salud** | Medicamentos, Suplementos, **Otros** |
| **Snacks** | Botanas, Dips, Frutos Secos, Palomitas, Papas Fritas, Totopos, **Otros** |

### Validation Rule for Suggested Fixes

Before suggesting a fix, verify:
1. The **category** is one of the 11 categories above
2. The **sub-category** is in that category's list
3. The pair `Category > Subcategory` is valid

**If invalid:** Write `INVALID TAXONOMY` in the Suggested Fix column and explain
what sub-category would be needed. Do NOT make up a sub-category name.

**Examples of what NOT to do:**
- ❌ Suggest "Snacks > Chips" — "Chips" is not a valid sub-category (use "Papas Fritas" or "Otros")
- ❌ Suggest "Bebidas > Energy Drink" — not valid (use "Refresco" or "Otros")
- ❌ Suggest "Carnes > Bacon" — not valid (use "Embutidos" or "Cerdo" or "Otros")
- ❌ Suggest "Lácteos > Yogur Griego" — not valid (use "Yogur" or "Otros")

**Examples of what TO do:**
- ✅ Suggest "Snacks > Papas Fritas" — valid
- ✅ Suggest "Snacks > Otros" — valid (when no specific sub-category fits)
- ✅ Mark "NEEDS TAXONOMY UPDATE: would need 'Snacks > Chips'" — valid response

---

## Batch Review: 50 Items Per Batch

Use the `batch_review` module to query batches for sub-agent review.

```bash
# Query batch 1 (first 50 items)
python -m v2.stage3b_classification_review.batch_review 0 50

# Query batch 2 (items 50-99)
python -m v2.stage3b_classification_review.batch_review 50 50

# Get total count and batch info
python -m v2.stage3b_classification_review.batch_review --count
python -m v2.stage3b_classification_review.batch_review --info

# Output as JSONL (for piping to files)
python -m v2.stage3b_classification_review.batch_review 0 50 --json
```

### What Each Row Includes

- **Item name** (receipt name)
- **Current label** (Spanish name, category, subcategory, source, confidence)
- **Purchase statistics** (count, stores, price range, total spend, quantity range)
- **Neighbours** (top 5 similar products with their categories)
- **Recent purchases** (last 3 purchases with date, store, price, quantity)

### As Python Module

```python
from v2.stage3b_classification_review.batch_review import query_batch, get_total_items

# Get total items
total = get_total_items()  # 1067

# Query a batch
rows = query_batch(offset=0, limit=50)
for row in rows:
    print(f"{row['item_name']}: {row['category']} > {row['subcategory']}")
    print(f"  Neighbours: {row['neighbours']}")
    print(f"  Recent: {row['recent_purchases']}")
```

### SQL Query (for reference)

The underlying SQL query is in `v2/stage3b_classification_review/batch_review.py` as `BATCH_QUERY`.

---

## Worker Prompt Template

Give each Explore subagent this prompt with the batch data:

```
You are auditing supermarket product classifications. Review these 50 items
and flag any that appear WRONGLY CLASSIFIED.

For each item, compare against:
- NEIGHBOURS: Similar products with their categories (are they consistent?)
- PRICE: Is the price reasonable for the category? (e.g., €0.50 for meat is suspicious)
- STORE: Does the product make sense for the store? (AH = Albert Heijn, Jumbo)
- QUANTITY: Is the quantity/unit sensible? (e.g., 0.001 kg = 1g might be a data error)

Also check:
- Spanish name matches the item (e.g., "Jamón" should be ham, not cheese)
- Category makes sense (e.g., ice cubes in "Bebidas > Agua" vs "Hogar > Otros")
- Similar items have consistent labels (e.g., "AH KIP" and "JUMBO KIP" should both be chicken)

⚠️ CRITICAL: THE TAXONOMY IS FROZEN. You may ONLY suggest fixes using the exact
category > subcategory pairs from this list. NEVER invent new sub-categories.
If no valid sub-category fits, use "Otros" or mark "NEEDS TAXONOMY UPDATE".

VALID TAXONOMY (127 pairs):
Bebidas: Agua, Café, Cerveza, Chocolate, Cóctel, Jugo, Refresco, Té, Vino, Otros
Carnes: Atún, Carne Molida, Cerdo, Embutidos, Jamón, Pescado, Pollo, Res, Vegetariana, Otros
Dulces: Barritas, Chocolate, Galletas, Golosinas, Helado, Pasteles, Postres, Untables, Otros
Frutas & Verduras: Ajo, Brócoli, Brotes, Calabacín, Cebolla, Champiñones, Conservas, Ejotes, Espinaca, Frambuesa, Fresa, Fruta Seca, Frutas, Hierbas Frescas, Lechuga, Limón, Maíz, Mandarina, Mango, Manzana, Mezcla de Verduras, Naranja, Papas, Pepino, Pera, Pimiento, Plátano, Sandía, Tomate, Uvas, Verduras, Zanahoria, Otros
Higiene: Afeitado, Algodón, Cuidado del Cabello, Dental, Higiene Femenina, Jabón, Pañuelos, Papel Higiénico, Toallitas, Otros
Hogar: Aceite y Vinagre, Ambientador, Baterías, Bolsas, Cereal, Condimentos, Conservas, Decoración, Desechables, Frijoles, Harina, Jardinería, Lavandería, Limpieza, Mascotas, Mermeladas, Papelería, Salsas, Utensilios de Cocina, Otros
Lácteos: Crema, Huevos, Leche, Leche Deslactosada, Leche Vegetal, Mantequilla, Queso, Yogur, Otros
Panadería: Focaccia, Pan, Pan Dulce, Pan Hamburguesa, Pan para Hotdog, Repostería, Tortilla, Otros
Pasta/Sopas: Arroz, Fideos Instantáneos, Granos, Pasta, Pasta Preparada, Pasta Rellena, Sopas, Otros
Salud: Medicamentos, Suplementos, Otros
Snacks: Botanas, Dips, Frutos Secos, Palomitas, Papas Fritas, Totopos, Otros

USER-CONFIRMED CORRECT LABELS (do not flag these):
- AH PIZZA = Panadería > Otros (pizza, not pasta)
- AH HAMSTER = Hogar > Mascotas (plush toy, not pet food)
- BREWDOG WING = Bebidas > Cerveza (it's a beer, not chicken wings)
- MACHINE VAAT = Hogar > Limpieza (dishwasher tablets, not razor)
- LIVING THING = Bebidas > Refresco (watermelon soda)
- LOEMPIA = Snacks > Botanas (spring roll)
- SODA STRAWS FIZZ = Dulces > Golosinas (Haribo candy, not straws)
- IJSBLOKJES / CASTLE IJSBLOKJES = Bebidas > Agua (ice cubes)
- JUMBO ITALIAANS STK = Lácteos > Queso (Italian herb cheese)
- IBERICO CURADO KRM = Lácteos > Queso (cured cheese)
- BUBBIES CHUR = Dulces > Helado (mochi ice cream)
- EXTRA = Dulces > Golosinas (chewing gum)
- SMART FRESH = Hogar > Utensilios de Cocina (food containers)
- JUMBO GOLDEN SCHAAL = Frutas & Verduras > Manzana (Golden Delicious apples)
- VERSTE PAPRIKAP GER = Hogar > Condimentos (smoked paprika)
- DIEPVRIESTAS = Hogar > Bolsas (insulated bag, not frozen potatoes)
- GECONDENSEERDE MELK = Lácteos > Otros (condensed milk)
- ZWARTE BONENSPREAD = Snacks > Dips (bean spread)
- AH TR HUMMUS = Snacks > Dips (hummus)

OUTPUT FORMAT (markdown table):

| Item | Current Label | Issue | Suggested Fix | Confidence |
|------|---------------|-------|---------------|------------|
| ITEM NAME | Category > Subcategory | Why it's wrong | Valid Category > Subcategory from taxonomy, or "Otros", or "NEEDS TAXONOMY UPDATE: ..." | high/medium/low |

⚠️ BEFORE SUBMITTING: Run the validator on your output!

```bash
# Save your table to a file, then validate:
python -m v2.stage3b_classification_review.validator --batch your_findings.md

# If exit code is 1, the validator will show you which suggestions are invalid
# and suggest corrections. Fix them and re-run until exit code is 0.
```

VALIDATION CHECKLIST before submitting:
[ ] Ran `python -m v2.stage3b_classification_review.validator --batch your_findings.md`
[ ] Exit code is 0 (no invalid suggestions)
[ ] Every "Suggested Fix" uses ONLY categories/sub-categories from the taxonomy
[ ] No invented sub-categories (e.g., no "Chips", "Energy Drink", "Bacon", "Yogur Griego")
[ ] If unsure, used "Otros" or marked "NEEDS TAXONOMY UPDATE"

Only include items you believe are WRONG. If all 50 look correct, say "No issues found in this batch."

DO NOT:
- Write to any files (except your findings output which the parent will save)
- Call any APIs
- Modify the database
- Flag user-confirmed labels as wrong
- Suggest changes based only on naming preferences (e.g., "Yogur" vs "Yogurt")
- Invent sub-categories that don't exist in the taxonomy
- Skip running the validator before submitting
```

---

## Orchestrator Workflow

1. **Export 22 batches** using the CLI above (offsets 0, 50, 100, ..., 1050)
2. **Save batches** to `processed/audits/<timestamp>/batches/batch_001.txt` etc.
3. **Spawn Explore subagents** — one per batch, starting with 2-4 concurrent
4. **Each worker** queries its batch, reviews, returns a markdown table
5. **Parent validates** all suggested fixes against the frozen taxonomy:
   - Check every "Suggested Fix" is a valid `Category > Subcategory` pair
   - Reject or flag any invented sub-categories
   - Move invalid suggestions to a separate "Needs Taxonomy Update" section
6. **Parent collects** all valid tables, deduplicates, writes `findings.md`
7. **Report to user** with high-confidence issues first

---

## Example Output

Worker returns:

```markdown
| Item | Current Label | Issue | Suggested Fix | Confidence |
|------|---------------|-------|---------------|------------|
| AH SCHEPIJS | Dulces > Helado | "Schepijs" is Schweppes ice cream, brand mismatch | Dulces > Helado (keep) or Bebidas > Refresco | medium |
| JUMBO FETA | Carnes > Cerdo | Feta is cheese, not pork | Lácteos > Queso | high |
| AH WINE | Hogar > Otros | Wine should be in Bebidas | Bebidas > Vino | high |
| KELLOGGS CORNFLAKES | Hogar > Cereal | Cereal is correct, but check if Dulces > Barritas fits better | Hogar > Cereal (keep) | low |
| SPECIAL CHIPS | Snacks > Otros | "Chips" would be ideal but not in taxonomy | Snacks > Papas Fritas (closest match) | medium |
| ENERGY DRINK X | Bebidas > Refresco | Energy drink, but no "Bebidas > Bebida Energética" exists | Bebidas > Refresco (keep) or NEEDS TAXONOMY UPDATE: Bebidas > Bebida Energética | low |
```

**Note:** The last two examples show correct handling — when a better sub-category
doesn't exist, use the closest valid one or mark `NEEDS TAXONOMY UPDATE`.
Never invent "Snacks > Chips" or "Bebidas > Bebida Energética".

---

## Label Validator Helper (FOR SUB-AGENTS)

**Use `v2.stage3b_classification_review.validator` to check your suggestions before submitting.**

This helper ensures you NEVER invent categories or sub-categories.

### Quick Usage

```bash
# Validate a single label
python -m v2.stage3b_classification_review.validator "Carnes" "Jamón"
# Output: Valid: True

# Validate and get correction for invalid label
python -m v2.stage3b_classification_review.validator "Snacks" "Chips"
# Output: Valid: False
#         Suggested correction: Snacks > Papas Fritas

# Validate a "Category > Subcategory" string
python -m v2.stage3b_classification_review.validator --suggest "Snacks > Chips"
# Output: Corrected: Snacks > Papas Fritas

# List all 127 valid labels
python -m v2.stage3b_classification_review.validator --list

# Validate an entire findings markdown file
python -m v2.stage3b_classification_review.validator --batch findings.md

# Interactive mode
python -m v2.stage3b_classification_review.validator
```

### As a Python Module

```python
from v2.stage3b_classification_review.validator import (
    validate_label,
    suggest_correction,
    validate_label_string,
)

# Validate category + subcategory
is_valid, msg = validate_label("Carnes", "Jamón")  # (True, "Valid")
is_valid, msg = validate_label("Snacks", "Chips")  # (False, "Invalid subcategory...")

# Get correction for invalid label
corrected = suggest_correction("Snacks", "Chips")  # "Snacks > Papas Fritas"
corrected = suggest_correction("Bebidas", "Energy Drink")  # "Bebidas > Refresco"
corrected = suggest_correction("Carnes", "Bacon")  # "Carnes > Cerdo"

# Validate a full "Category > Subcategory" string
is_valid, msg, corrected = validate_label_string("Snacks > Chips")
# (False, "Invalid subcategory...", "Snacks > Papas Fritas")
```

### Common Mistakes → Auto-Corrections

The helper knows these common mistakes and will auto-correct them:

| You Write | Helper Corrects To |
|-----------|-------------------|
| Snacks > Chips | Snacks > Papas Fritas |
| Snacks > Crisps | Snacks > Papas Fritas |
| Snacks > Nachos | Snacks > Totopos |
| Snacks > Popcorn | Snacks > Palomitas |
| Bebidas > Soda | Bebidas > Refresco |
| Bebidas > Energy Drink | Bebidas > Refresco |
| Bebidas > Juice | Bebidas > Jugo |
| Carnes > Chicken | Carnes > Pollo |
| Carnes > Beef | Carnes > Res |
| Carnes > Bacon | Carnes > Cerdo |
| Carnes > Ham | Carnes > Jamón |
| Dulces > Candy | Dulces > Golosinas |
| Dulces > Ice Cream | Dulces > Helado |
| Dulces > Cookies | Dulces > Galletas |
| Lácteos > Milk | Lácteos > Leche |
| Lácteos > Yogurt | Lácteos > Yogur |
| Lácteos > Cheese | Lácteos > Queso |
| ... and 100+ more common translations | |

### Required Workflow for Sub-Agents

**BEFORE submitting your findings table:**

```bash
# 1. Save your findings to a temp file
# 2. Run the validator
.venv/bin/python scripts/validate_label.py --batch your_findings.md

# 3. If it exits with code 1, fix the invalid suggestions using the corrections provided
# 4. Re-run until exit code is 0
# 5. Then submit your corrected findings
```

**OR validate inline while generating:**

```python
# In your reasoning, before writing a suggestion:
from scripts.validate_label import validate_label_string

suggested = "Snacks > Chips"
is_valid, msg, corrected = validate_label_string(suggested)
if not is_valid:
    suggested = corrected  # Use "Snacks > Papas Fritas" instead
```

---

## Parent Validation

Parent uses this after collecting all worker results:

```bash
# Validate the final findings file
python -m v2.stage3b_classification_review.validator --batch processed/audits/<timestamp>/findings.md

# If exit code is 1, workers invented sub-categories — review and correct
# If exit code is 0, all suggestions are valid
```

---

## Final Report Structure

```markdown
# Classification Audit Findings

## Summary
- Batches reviewed: 22/22
- Items reviewed: 1,067
- Flagged: XX items
- High confidence: XX
- Medium confidence: XX
- Low confidence: XX
- Invalid taxonomy suggestions caught: XX

## High Confidence Issues
| Item | Current | Issue | Suggested |
|------|---------|-------|-----------|

## Medium Confidence Issues
| Item | Current | Issue | Suggested |
|------|---------|-------|-----------|

## Needs Taxonomy Update
Items that seem correct but need a new sub-category:

| Item | Current | Issue | Needed Sub-Category |
|------|---------|-------|-------------------|

## Needs Confirmation
| Item | Current | Uncertainty |
|------|---------|-------------|

## No Issues Found
XX items reviewed with no concerns.
```

---

## Quick Start

```bash
# 1. Create audit directory
mkdir -p processed/audits/$(date +%Y%m%d_%H%M%S)/batches
AUDIT_DIR=$(ls -td processed/audits/*/ | head -1)

# 2. Export all 22 batches
for i in $(seq 0 50 1050); do
  batch_num=$((i / 50 + 1))
  .venv/bin/python - $i 50 <<'PY' > "${AUDIT_DIR}batches/batch_$(printf %03d $batch_num).txt"
# ... (use the CLI script above)
PY
done

# 3. Spawn Explore subagents (one per batch file)
# 4. Collect results into findings.md
```
