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
- Name the food, not how it is sold or cooked. Drop:
  cuisine/style words (italiana, mexicana, provenzal, holandesa, oriental, clásica),
  cooking method or use (para saltear, para wok, para horno, para hornear, para ensalada),
  cut or preparation (picada, rallada, en rodajas, lavada, cortada),
  add-ins and component lists ("con maíz y rábanos", "(calabacín, pimiento y zanahoria)").
- Never use parentheses. Use at most 4 words.
- Mixes are named by what they are, not by their flavour: "mezcla de verduras", "ensalada mixta".
- Keep a separate name only if a recipe would ask for it by that name and another product
  in the group could not replace it ("verduras para sopa", "hutspot", "lechuga iceberg").
- When unsure between a specific and a broader name, choose the broader one.
- Trust the Dutch receipt name when the Spanish name looks like a bad translation
  (AH KOOL PEEN is a cabbage-and-carrot mix, not "col rallada").
- Non-food products (cleaning, personal care, pets, household) get a generic product name instead
  ("champú", "detergente en cápsulas", "esponja") with is_food=false.
- If an existing ingredient below is the same thing, copy its name exactly. Only invent a new name when
  none fits.

Examples (wrong -> right):
  mezcla italiana para saltear              -> mezcla de verduras
  verduras para horno (calabacín, pimiento) -> mezcla de verduras
  lechuga iceberg con maíz y rábanos        -> ensalada mixta
  espinaca baby orgánica                    -> espinaca

Every product number must appear in exactly one group.
confidence: high = every product in the group is clearly the same food;
medium = you merged products whose descriptions differ;
low = the Dutch and Spanish names disagree or you are guessing.
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
