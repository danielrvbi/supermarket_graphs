# Stage 3B: Classification Review

Tools for reviewing, auditing, and validating product classifications from Stage 3.

## Overview

Stage 3B provides:
- **CLI** for manual review (list, show, approve, set, taxonomy)
- **Validator** to prevent invented categories/sub-categories
- **Batch review** queries for automated sub-agent audits
- **Handoff documentation** for audit workflows

## Quick Start

### Manual Review

```bash
# List items flagged for review
python -m v2.stage3b_classification_review.cli list

# List all LLM labels
python -m v2.stage3b_classification_review.cli list --all

# Show one label with evidence
python -m v2.stage3b_classification_review.cli show "AH KIPFI"

# Approve a label (clear review flag)
python -m v2.stage3b_classification_review.cli approve "AH KIPFI"

# Set a manual label
python -m v2.stage3b_classification_review.cli set "AH KIPFI" Carnes Pollo --producto "Pechuga de Pollo AH"

# Show valid taxonomy
python -m v2.stage3b_classification_review.cli taxonomy
```

### Validate Labels

```bash
# Validate a label
python -m v2.stage3b_classification_review.validator "Carnes" "Jamón"

# Validate and get correction
python -m v2.stage3b_classification_review.validator "Snacks" "Chips"
# Output: Suggested correction: Snacks > Papas Fritas

# List all 127 valid labels
python -m v2.stage3b_classification_review.validator --list

# Validate a findings file
python -m v2.stage3b_classification_review.validator --batch findings.md
```

### Batch Review (for Sub-Agents)

```bash
# Query batch 1 (first 50 items)
python -m v2.stage3b_classification_review.batch_review 0 50

# Query batch 2 (items 50-99)
python -m v2.stage3b_classification_review.batch_review 50 50

# Get total count
python -m v2.stage3b_classification_review.batch_review --count

# Output as JSONL
python -m v2.stage3b_classification_review.batch_review 0 50 --json

# Batch info
python -m v2.stage3b_classification_review.batch_review --info
```

## Module Structure

```
v2/stage3b_classification_review/
├── __init__.py           # Package exports
├── cli.py                # Manual review CLI
├── validator.py          # Label validator (prevents invented categories)
├── batch_review.py       # Batch queries for sub-agent audits
├── HANDOFF.md            # Audit workflow documentation
├── README.md             # This file
└── tests/
    ├── __init__.py
    └── test_validator.py # Validator tests
```

## Validator: Preventing Invented Categories

The validator ensures sub-agents **NEVER invent new categories or sub-categories**.

### Common Mistakes Auto-Corrected

| You Write | Corrected To |
|-----------|--------------|
| Snacks > Chips | Snacks > Papas Fritas |
| Bebidas > Soda | Bebidas > Refresco |
| Bebidas > Energy Drink | Bebidas > Refresco |
| Carnes > Chicken | Carnes > Pollo |
| Carnes > Bacon | Carnes > Cerdo |
| Dulces > Ice Cream | Dulces > Helado |
| Lácteos > Cheese | Lácteos > Queso |
| Frutas & Verduras > Apple | Frutas & Verduras > Manzana |

### As Python Module

```python
from v2.stage3b_classification_review.validator import (
    validate_label,
    validate_label_string,
    suggest_correction,
)

# Validate
is_valid, msg = validate_label("Carnes", "Jamón")  # (True, "Valid")
is_valid, msg = validate_label("Snacks", "Chips")  # (False, "Invalid subcategory...")

# Auto-correct
corrected = suggest_correction("Snacks", "Chips")  # "Snacks > Papas Fritas"

# Validate string
is_valid, msg, corrected = validate_label_string("Snacks > Chips")
# (False, "Invalid subcategory...", "Snacks > Papas Fritas")
```

## Batch Review for Sub-Agents

The batch review query returns one row per unique item with:
- Current label (Spanish name, category, subcategory, source, confidence)
- Purchase statistics (count, stores, price range, total spend, quantity range)
- Top 5 neighbours (similar products with their categories)
- Recent 3 purchases (date, store, price, quantity)

### Example Output

```
Item                   | Spanish Name                   | Category               | Src        | Conf  | #   | Stores     | Price           | Neighbours
--------------------------------------------------------------------------------------------------------------------------------------------------------------------
AH KIPFI               | Pechuga de Pollo AH            | Carnes > Pollo         | embed_llm  | 0.9   | 2   | ah         | EUR 3.5-3.99    | AH KIP [Carnes > Pollo] | AH BIO KIP [Carnes > Pollo]
                       | Recent: 2026-09-08 ah EUR 7.0 (x2) | 2026-03-15 ah EUR 3.99 (x1)
```

## Frozen Taxonomy

The taxonomy is **FROZEN** with 127 valid `Category > Subcategory` pairs.

| Category | Count | Sub-Categories |
|----------|------:|----------------|
| Bebidas | 10 | Agua, Café, Cerveza, Chocolate, Cóctel, Jugo, Refresco, Té, Vino, Otros |
| Carnes | 10 | Atún, Carne Molida, Cerdo, Embutidos, Jamón, Pescado, Pollo, Res, Vegetariana, Otros |
| Dulces | 9 | Barritas, Chocolate, Galletas, Golosinas, Helado, Pasteles, Postres, Untables, Otros |
| Frutas & Verduras | 30 | Ajo, Brócoli, ..., Zanahoria, Otros |
| Higiene | 10 | Afeitado, Algodón, ..., Toallitas, Otros |
| Hogar | 20 | Aceite y Vinagre, ..., Utensilios de Cocina, Otros |
| Lácteos | 9 | Crema, Huevos, ..., Yogur, Otros |
| Panadería | 8 | Focaccia, Pan, ..., Tortilla, Otros |
| Pasta/Sopas | 8 | Arroz, ..., Sopas, Otros |
| Salud | 3 | Medicamentos, Suplementos, Otros |
| Snacks | 7 | Botanas, Dips, ..., Totopos, Otros |

**Total: 127 valid pairs**

See `python -m v2.stage3b_classification_review.validator --list` for the full list.

## Audit Workflow

See [HANDOFF.md](HANDOFF.md) for the complete audit workflow using Explore sub-agents.

## Migration from Stage 3

The review functionality was moved from `v2/stage3_classification/review/` to this
folder. The old path still works via `v2/main.py` for backwards compatibility.

```bash
# Old (still works)
python -m v2.main review-labels list

# New (preferred)
python -m v2.stage3b_classification_review.cli list
```

## Files

| File | Purpose |
|------|---------|
| `cli.py` | Manual review CLI (list, show, approve, set, taxonomy, validate, batch) |
| `validator.py` | Label validator with 200+ common mistake corrections |
| `batch_review.py` | SQL queries and utilities for batch audits |
| `HANDOFF.md` | Complete audit workflow documentation |
| `tests/test_validator.py` | Validator unit tests |
