"""
Stage 3C - v2 taxonomy.

New category / subcategory / product_category tables next to the untouched v1 labels,
a v1 -> v2 map, and a re-runnable sync (1:1 mappings + LLM for splits).

Usage:
    python -m v2.stage3c_taxonomy.cli init
    python -m v2.stage3c_taxonomy.cli sync --dry-run
    python -m v2.stage3c_taxonomy.cli show --counts
"""
