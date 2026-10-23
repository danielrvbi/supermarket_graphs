# Stage 1 — Extraction

**Input:** `raw_receipts/ah/*.pdf`, `raw_receipts/jumbo/*.png`
**Output:** `processed_data` table (`store.py`) + `processed/v2_*_{clean,review,rejected}.json`

LangGraph pipeline per store (`ah/`, `jumbo/`): preprocess → deterministic → llm_extract →
merge → validate → verify → correct → finalize. Checkpoints in `v2/checkpoints/`.

```bash
python -m v2.main extract ah <receipt.pdf>         # one receipt
python -m v2.main extract-batch jumbo <folder>     # one folder
python -m v2.main extract-all                      # everything not yet in processed_data
python -m v2.main test ah|jumbo|all                # live tests (calls Mistral)
python -m v2.stage1_extraction.review.cli list --ah
```
