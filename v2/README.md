# V2 Supermarket Receipt Pipeline

Deterministic + AI-validated extraction for AH (PDF) and Jumbo (image) receipts.

**Tech Stack:** LangChain + LangGraph + Mistral API (mistral-small-latest)

---

## Stages

Like v1 (`step1_extraction.py` → `step2_normalization.py` → ...), v2 runs as a sequence
of stages. Each stage lives in its own folder and hands off to the next through a table
in `processed/processed_data.db`.

| Stage | Folder | Input | Output | Run |
|-------|--------|-------|--------|-----|
| 1. Extraction | `stage1_extraction/` | `raw_receipts/` | `processed_data` | `python -m v2.main extract-all` |
| 2. Normalization | `stage2_normalization/` | `processed_data` | `normalized_data` | `python -m v2.main normalize` |
| 3. Classification | `stage3_classification/` | `normalized_data` + `old_data.csv` | `item_labels`, `classified_data` | `python -m v2.main classify` |
| 3D. Ingredients | `stage3d_ingredients/` | `item_labels` + v2 taxonomy (3C) | `ingredient`, `product_ingredient` | `python -m v2.main ingredients assign ...` |
| 4. Graph db | `stage4_graph_db/` | processing db (all of the above) | `processed/graph.db` (separate file, rebuilt) | `python -m v2.main graph-db` |

Rule: a stage imports from `common/` and may read the previous stage's `store.py`, never a later stage.

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Environment

```bash
cp .env.example .env
# Edit .env and add your MISTRAL_KEY
```

Get your Mistral API key from: https://console.mistral.ai/

### 3. Run Live Tests (4 AH + 4 Jumbo receipts)

```bash
# Test AH pipeline (4 receipts: earliest, early, middle, latest)
python -m v2.stage1_extraction.tests.test_live ah

# Test Jumbo pipeline (4 receipts: earliest, early, middle, latest)
python -m v2.stage1_extraction.tests.test_live jumbo

# Test both
python -m v2.stage1_extraction.tests.test_live all
```

### 4. Process Receipts

```bash
# Process single receipt
python -m v2.main extract ah "raw_receipts/ah/AH_kassabon_YYYY-MM-DD_HHMM_STORE.pdf"
python -m v2.main extract jumbo "raw_receipts/jumbo/receipt.png"

# Process entire folder
python -m v2.main extract-batch ah raw_receipts/ah
python -m v2.main extract-batch jumbo raw_receipts/jumbo

# Show statistics
python -m v2.main stats
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SHARED COMPONENTS                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │   Config    │  │   Schemas   │  │  Validators │  │  Output Writer  │ │
│  │ (MISTRAL_   │  │  (v1-compatible│ │ (deterministic│ │ (clean/review/  │ │
│  │   KEY)      │  │   schema)   │  │   checks)   │  │   rejected)     │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│      AH PIPELINE (PDF)          │   │    JUMBO PIPELINE (Image)       │
│  Checkpoints: ah_pipeline.db    │   │  Checkpoints: jumbo_pipeline.db │
│                                 │   │                                 │
│  1. preprocess (pdfplumber)     │   │  1. preprocess (OCR/crop)       │
│  2. deterministic (regex)       │   │  2. deterministic (regex)       │
│  3. llm_extract (mistral)       │   │  3. llm_extract (mistral)       │
│  4. merge                       │   │  4. merge                       │
│  5. validate (shared)           │   │  5. validate (shared)           │
│  6. verify (AH-specific)        │   │  6. verify (Jumbo-specific)     │
│  7. correct (if needed)         │   │  7. correct (if needed)         │
│  8. finalize → output           │   │  8. finalize → output           │
└─────────────────────────────────┘   └─────────────────────────────────┘
```

---

## Pipeline Flow

```
preprocess → deterministic → llm_extract → merge → validate
                                                          │
                                    ┌─────────────────────┘
                                    ▼
                              ┌─────────┐
                              │ verify? │ ──No──▶ finalize
                              └────┬────┘
                                   │Yes
                                   ▼
                              ┌─────────┐
                              │ verify  │
                              └────┬────┘
                                   ▼
                              ┌─────────┐
                              │correct? │ ──No──▶ finalize
                              └────┬────┘
                                   │Yes
                                   ▼
                              ┌─────────┐
                              │ correct │──▶ validate (loop)
                              └─────────┘
```

---

## Checkpoints & Debugging

Every node execution is saved to a SQLite database. You can inspect and resume from any point.

```python
from v2.stage1_extraction.debug.inspect import inspect_receipt, list_checkpoints
from v2.stage1_extraction.debug.resume import resume_failed_receipt

# Inspect a receipt's pipeline flow
inspect_receipt("ah_AH_kassabon_YYYY-MM-DD_HHMM_STORE", store="ah")

# List all checkpoints
checkpoints = list_checkpoints("ah_AH_kassabon_YYYY-MM-DD_HHMM_STORE", store="ah")

# Resume a failed pipeline
resume_failed_receipt(pipeline, "ah_AH_kassabon_YYYY-MM-DD_HHMM_STORE", store="ah")
```

Or via CLI:

```bash
python -m v2.main inspect ah_AH_kassabon_YYYY-MM-DD_HHMM_STORE ah
```

---

## Review Queue

Receipts with confidence < 0.95 go to the review queue.

```bash
# List receipts needing review
python -m v2.stage1_extraction.review.cli list --ah
python -m v2.stage1_extraction.review.cli list --jumbo

# Show receipt details
python -m v2.stage1_extraction.review.cli show "raw_receipts/ah/..." --ah

# Approve a receipt
python -m v2.stage1_extraction.review.cli approve "raw_receipts/ah/..." --ah

# Reject a receipt
python -m v2.stage1_extraction.review.cli reject "raw_receipts/ah/..." --ah
```

---

## Output Files

All output goes to `processed/` (v1 files are untouched):

| File | Description |
|------|-------------|
| `v2_ah_clean.json` | Auto-approved AH receipts |
| `v2_ah_review.json` | AH receipts needing human review |
| `v2_ah_rejected.json` | Failed AH receipts |
| `v2_jumbo_clean.json` | Auto-approved Jumbo receipts |
| `v2_jumbo_review.json` | Jumbo receipts needing human review |
| `v2_jumbo_rejected.json` | Failed Jumbo receipts |
| `v2_audit_log.json` | Full audit trail of all decisions |

---

## Stage 2: Normalization

After extraction, run the deterministic normalization script to clean and standardize data.

**No LLM calls — 100% deterministic rules ported from V1 `step2_normalization.py`.**

### Usage

```bash
# Normalize all receipts (reads processed_data, writes normalized_data)
python -m v2.main normalize

# Normalize specific store
python -m v2.main normalize --store ah
python -m v2.main normalize --store jumbo

# Clear and rebuild normalized table
python -m v2.main normalize --rebuild

# Preview changes without writing
python -m v2.main normalize --dry-run

# Limit items (for testing)
python -m v2.main normalize --limit 100
```

### What It Does

| Rule | Description | Example |
|------|-------------|---------|
| `name_uppercase` | Standardize item names | `"cola zero"` → `"COLA ZERO"` |
| `date_standardized` | Normalize dates to ISO format | `"2024/03/08"` → `"2024-03-08"` |
| `date_parse_dutch` | Parse Dutch dates (Jumbo) | `"19 januari 2026"` → `"2026-01-19"` |
| `month_derived` | Add month for grouping | `"2026-01-19"` → `"2026-01-01"` |
| `weight_to_kg` | Convert grams to kg | `250g` → `0.25 kg` |
| `clean_scharrelei` | Detect egg pack size by price | `€6.99` → 20-pack, `€2.49` → 6-pack |
| `clean_bundle_plus` | Parse "10+2" bundles | `"COLA 10+2"` → qty=12 |
| `clean_bundle_x` | Parse "12X330" bundles | `"BIER 12X330"` → qty=12 |
| `clean_pack_identifier` | Extract pack sizes | `"HEINEKEN 12P"` → qty=12 |
| `clean_trailing_price` | Remove price artifacts | `"HAM 3,75"` → `"HAM"` |
| `fix_line_total_from_qty_times_price` | Fix total = qty × price | AH arithmetic fix |
| `fix_quantity_from_total_div_price` | Fix qty = total / price | AH arithmetic fix |
| `price_recalc` | Calculate missing ppu | Jumbo: `ppu = total / qty` |
| `price_recalc_final` | Final ppu = total / qty | After all cleaning |
| `filter_stati` | Remove deposit items | Filter "STATIEGELD" items |
| `round_values` | Round to 3 decimals | `1.23456` → `1.235` |

### Database Tables

| Table | Description | Rows |
|-------|-------------|------|
| `processed_data` | Raw extracted data (unchanged) | 3,205 items |
| `normalized_data` | Cleaned, standardized data | 3,165 items |

**Note:** `normalized_data` has fewer rows due to UNIQUE constraint deduplication.

### Example: Before vs After

**Before (processed_data):**
```json
{
  "item_name": "HEINEKEN 12P",
  "measurement_quantity": 1.0,
  "price_per_measurement_unit": 12.15,
  "line_total_paid_amount": 12.15
}
```

**After (normalized_data):**
```json
{
  "item_name": "HEINEKEN",
  "measurement_quantity": 12.0,
  "price_per_measurement_unit": 1.01,
  "line_total_paid_amount": 12.15,
  "normalization_rules": ["name_uppercase", "clean_pack_identifier", "price_recalc_final", ...]
}
```

### Querying Normalized Data

```sql
-- Price history for an item
SELECT date_of_purchase, store, price_per_measurement_unit
FROM normalized_data
WHERE item_name = 'COLA ZERO'
ORDER BY date_of_purchase;

-- Monthly spending by category
SELECT month_of_purchase, store, SUM(line_total_paid_amount) as total
FROM normalized_data
GROUP BY month_of_purchase, store;

-- Average price per item
SELECT item_name, AVG(price_per_measurement_unit) as avg_price, COUNT(*) as purchases
FROM normalized_data
GROUP BY item_name
ORDER BY avg_price DESC;
```

---

## Output Schema (V1-Compatible)

```json
{
  "raw_receipts/ah/AH_kassabon_YYYY-MM-DD_HHMM_STORE.pdf": {
    "date_of_purchase": "2024/03/08",
    "items": [
      {
        "item_name": "COLA ZERO FL",
        "measurement_type": "discrete_units",
        "measurement_quantity": 3.0,
        "price_per_measurement_unit": 1.79,
        "line_total_paid_amount": 5.37
      }
    ]
  }
}
```

---

## Validation Rules

| Check | Description | Tolerance |
|-------|-------------|-----------|
| Arithmetic | quantity × unit_price ≈ line_total | €0.02 |
| Reconciliation | sum of items ≈ receipt total | €0.05 |
| Duplicates | Same item + same price on one receipt | Warning |
| Sanity | Prices > 0, < €100; weights 1g-10kg | Warning |
| Date | Not future, not before 2020 | Error |

---

## Confidence Scoring

Overall confidence is a weighted average of:

| Factor | Weight |
|--------|--------|
| Validation passed | 20% |
| Arithmetic OK | 20% |
| Reconciliation OK | 20% |
| Verification confidence | 20% |
| No duplicates | 10% |
| OCR quality (Jumbo only) | 10% |

**Thresholds:**
- ≥ 0.95: Auto-approve (clean)
- 0.70 - 0.94: Review queue
- < 0.70: Rejected

---

## Test Files

Test receipts are configured in `v2/stage1_extraction/tests/test_files.local.json` (gitignored, since
filenames contain purchase dates and store numbers). Copy
`v2/stage1_extraction/tests/test_files.example.json` and fill in your own paths.

### AH (4 receipts)
| ID | Period |
|----|--------|
| AH-1 | Earliest |
| AH-2 | Early |
| AH-3 | Middle |
| AH-4 | Latest |

### Jumbo (4 receipts)
| ID | Period |
|----|--------|
| J-1 | Earliest |
| J-2 | Early |
| J-3 | Middle |
| J-4 | Latest |

---

## Folder Structure

```
v2/
├── main.py                  # Unified CLI, dispatches to stage runners
├── common/                  # Cross-stage infrastructure
│   ├── settings.py          # Settings (MISTRAL_KEY, paths, thresholds)
│   ├── db.py                # SQLiteStore base class for stage tables
│   ├── mistral_client.py    # Mistral LLM factory
│   ├── token_tracker.py     # Token usage tracking
│   ├── pricing.py           # Model pricing
│   └── cost_report.py       # Cost reports
├── stage1_extraction/       # Stage 1: raw receipts → processed_data
│   ├── run.py               # Single / folder / all-remaining runners
│   ├── store.py             # processed_data table
│   ├── schemas.py           # V1-compatible Pydantic models
│   ├── output_writer.py     # clean/review/rejected JSON + DB insert
│   ├── audit_log.py         # Decision audit trail
│   ├── validators/          # arithmetic, reconciliation, duplicates, sanity
│   ├── ah/                  # AH-specific (PDF)
│   │   ├── preprocess.py    # pdfplumber extraction
│   │   ├── deterministic.py # Regex table parser
│   │   ├── llm_extract.py   # Mistral extraction
│   │   ├── verifier.py      # AH AI verifier
│   │   ├── graph.py         # LangGraph assembly
│   │   └── prompts.py       # AH prompts
│   ├── jumbo/               # Jumbo-specific (Image), same layout as ah/
│   ├── debug/               # Inspect/resume LangGraph checkpoints
│   ├── review/              # CLI review interface
│   └── tests/               # Live test runner (calls Mistral)
├── stage2_normalization/    # Stage 2: processed_data → normalized_data
│   ├── run.py               # Normalization CLI
│   ├── store.py             # normalized_data table
│   ├── normalizer.py        # Main orchestrator
│   ├── rules/               # Individual cleaning rules
│   │   ├── item_cleaner.py      # Edge cases (eggs, bundles, packs)
│   │   ├── date_parser.py       # Dutch date parsing
│   │   ├── unit_normalizer.py   # Weight g→kg conversion
│   │   ├── arithmetic_fixer.py  # Fix qty × price ≠ total
│   │   └── name_standardizer.py # Name cleanup
│   └── tests/               # Deterministic unit tests (pytest)
├── stage3_classification/   # Stage 3: normalized_data → classified_data (see its README)
├── stage3d_ingredients/     # Stage 3D: product → ingredient (see its README / HANDOFF)
├── stage4_graph_db/         # Stage 4: processed/graph.db, the clean db for graph ingestion
└── checkpoints/             # LangGraph SQLite databases (gitignored)
```

---

## Troubleshooting

### "MISTRAL_KEY not set"
```bash
# Add to .env file
MISTRAL_KEY=your-key-here
```

### "No module named 'pdfplumber'" / "No module named 'cv2'"
```bash
pip install -r requirements.txt
```

### Pipeline fails at a node
```bash
# Inspect checkpoints to see where it failed
python -m v2.main inspect <thread_id> ah

# Resume from last checkpoint
from v2.stage1_extraction.debug.resume import resume_failed_receipt
resume_failed_receipt(pipeline, thread_id, store="ah")
```

### Low OCR quality for Jumbo
- Check the original image quality
- The verifier accounts for OCR errors (lower confidence threshold)
- Receipts with OCR quality < 0.7 always go through AI verification

---

## Cost Estimation (Mistral Small)

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| mistral-small-latest | ~$0.10 | ~$0.30 |

**Estimated cost per receipt:** ~$0.005-0.01
**For 632 receipts (478 AH + 154 Jumbo):** ~$3-6 total
