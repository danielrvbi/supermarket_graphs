# V2 Supermarket Receipt Pipeline

Deterministic + AI-validated extraction for AH (PDF) and Jumbo (image) receipts.

**Tech Stack:** LangChain + LangGraph + Mistral API (mistral-small-latest)

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
python -m v2.tests.test_live ah

# Test Jumbo pipeline (4 receipts: earliest, early, middle, latest)
python -m v2.tests.test_live jumbo

# Test both
python -m v2.tests.test_live all
```

### 4. Process Receipts

```bash
# Process single receipt
python -m v2.main ah "raw_receipts/ah/AH_kassabon_YYYY-MM-DD_HHMM_STORE.pdf"
python -m v2.main jumbo "raw_receipts/jumbo/receipt.png"

# Process entire folder
python -m v2.main ah-batch raw_receipts/ah
python -m v2.main jumbo-batch raw_receipts/jumbo

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
from v2.debug.inspect import inspect_receipt, list_checkpoints
from v2.debug.resume import resume_failed_receipt

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
python -m v2.review.cli list --ah
python -m v2.review.cli list --jumbo

# Show receipt details
python -m v2.review.cli show "raw_receipts/ah/..." --ah

# Approve a receipt
python -m v2.review.cli approve "raw_receipts/ah/..." --ah

# Reject a receipt
python -m v2.review.cli reject "raw_receipts/ah/..." --ah
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

Test receipts are configured in `v2/tests/test_files.local.json` (gitignored, since
filenames contain purchase dates and store numbers). Copy
`v2/tests/test_files.example.json` and fill in your own paths.

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
├── config/           # Settings (MISTRAL_KEY, thresholds)
├── schemas/          # V1-compatible Pydantic models
├── shared/           # Validators, output writer, audit log, Mistral client
│   └── validators/   # arithmetic, reconciliation, duplicates, sanity
├── ah_pipeline/      # AH-specific (PDF)
│   ├── preprocess.py    # pdfplumber extraction
│   ├── deterministic.py # Regex table parser
│   ├── llm_extract.py   # Mistral extraction
│   ├── verifier.py      # AH AI verifier
│   ├── graph.py         # LangGraph assembly
│   └── prompts.py       # AH prompts
├── jumbo_pipeline/   # Jumbo-specific (Image)
│   ├── preprocess.py    # OCR + crop
│   ├── deterministic.py # Regex line parser
│   ├── llm_extract.py   # Mistral extraction
│   ├── verifier.py      # Jumbo AI verifier
│   ├── graph.py         # LangGraph assembly
│   └── prompts.py       # Jumbo prompts
├── checkpoints/      # SQLite databases
├── debug/            # Inspect/resume tools
├── review/           # CLI review interface
└── tests/            # Live test runner
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
from v2.debug.resume import resume_failed_receipt
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
