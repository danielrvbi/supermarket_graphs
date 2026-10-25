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

## Receipt output consistency

Receipt JSON and the aggregate JSON backup are staged in temporary sibling files before
publication. Clean receipts are validated and written within a SQLite transaction; the
files are published before that transaction commits. Rejected reprocessing leaves existing
files and database rows unchanged. Review and rejected outputs use the same staged file
publication without writing product rows.

Ordinary database or publication failures roll back SQL and restore the previous file
contents (or remove files that did not previously exist). The writer's in-memory backup
advances only after success. If restoration itself fails, the error identifies retained
recovery copies. This covers exception rollback, not crash recovery across SQLite and files.
