"""
Prompts for stage 3C (splitting a v1 subcategory into v2 subcategories).
"""

SPLIT_SYSTEM_PROMPT = """You re-file Dutch supermarket products (Albert Heijn, Jumbo) for a Spanish-speaking household's budget.

A product category is being split into finer subcategories. For every product in the list, pick exactly one
label from the allowed labels. Each product line is: number. receipt name | Spanish product name | store.
The Spanish name is usually right but can be a poor translation (e.g. Dutch "pastasaus" = pasta sauce,
even if it was translated as "Pasta Italiana ..."), so use the receipt name too.

Return one assignment per product: its number (id) and the label copied exactly from the allowed labels.
confidence: high = clearly fits; medium = most likely; low = guessing or none of the labels fits well.
"""

SPLIT_USER_PROMPT_TEMPLATE = """Current label: {v1_label}

Allowed labels:
{candidates}

Products:
{products}"""
