"""
Prompts for stage 3D (grouping one v2 subcategory's products into ingredients).
"""

INGREDIENT_SYSTEM_PROMPT = """You map Dutch supermarket products (Albert Heijn, Jumbo) to generic ingredients for a Spanish-speaking household.

You get every product of one subcategory at once, from both stores. Group the products that are the same
generic thing and give each group one ingredient name. Products from different stores and brands that are
the same food MUST share the same ingredient. Each product line is: number. receipt name | Spanish product name | store.
The Spanish name is usually right but can be a poor translation, so use the Dutch receipt name too.

Ingredient names:
- Spanish, lowercase, singular: "fresa", "espinaca", "leche de avena", "mozzarella", "atún en conserva".
- Generic: no brand (AH, Jumbo, Oatly, Heinz...), no bio/orgánico, no size, weight, pack or quantity,
  no marketing variants (barista, extra, original, light...) unless it changes what the food is
  ("leche" vs "leche sin lactosa" is fine to keep apart; "manzana pink lady" is just "manzana").
- Prefer the most common everyday name a recipe would use.
- Non-food products (cleaning, personal care, pets, household) get a generic product name instead
  ("champú", "detergente en cápsulas", "esponja") with is_food=false.
- If an existing ingredient below is the same thing, copy its name exactly. Only invent a new name when
  none fits.

Every product number must appear in exactly one group.
confidence: high = clearly this ingredient; medium = most likely; low = guessing.
reasoning: a few words.
"""

INGREDIENT_USER_PROMPT_TEMPLATE = """Subcategory: {subcategory}

Existing ingredients (reuse when it is the same thing):
{vocabulary}

Products:
{products}"""


def render_products(products) -> str:
    return "\n".join(
        f"{i}. {p['item_name']} | {p['producto_es'] or ''} | {p['store'] or ''}"
        for i, p in enumerate(products, 1)
    )


def render_vocabulary(vocabulary) -> str:
    return "\n".join(f"- {v}" for v in vocabulary) if vocabulary else "(none yet)"
