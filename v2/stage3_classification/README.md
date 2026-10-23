# Stage 3 — Classification (planned)

**Input:** `normalized_data` table (read via `v2.stage2_normalization.store.NormalizedDataStore`)
**Output:** `classified_data` table

Port of v1 `step3_classify.py`: assign each item a Spanish name, category and subcategory.

Suggested layout, mirroring the earlier stages:

```
stage3_classification/
├── run.py      # CLI, wired into `python -m v2.main classify`
├── store.py    # classified_data table (subclass of v2.common.db.SQLiteStore)
└── tests/
```
