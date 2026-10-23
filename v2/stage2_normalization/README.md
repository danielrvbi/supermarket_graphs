# Stage 2 — Normalization

**Input:** `processed_data` table (read via `v2.stage1_extraction.store.ProcessedDataStore`)
**Output:** `normalized_data` table (`store.py`)

Deterministic, no LLM calls. Rules in `rules/` are ported from v1 `step2_normalization.py`.

```bash
python -m v2.main normalize [--store ah|jumbo] [--rebuild] [--dry-run] [--limit N]
python -m pytest v2/stage2_normalization/tests
```
