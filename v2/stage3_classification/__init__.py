"""
Stage 3 - Classification.

`normalized_data` table -> `item_labels` (product dictionary) + `classified_data` table.
old_data.csv exact match -> Mistral embedding neighbours -> Tavily search (cached) -> Mistral label.
"""
