"""
Label validator for classification review.

Ensures sub-agents NEVER invent new categories or sub-categories.
Validates against the frozen taxonomy in v2.stage3_classification.taxonomy.

Usage as CLI:
    python -m v2.stage3b_classification_review.validator "Carnes" "Jamón"
    python -m v2.stage3b_classification_review.validator "Snacks" "Chips"
    python -m v2.stage3b_classification_review.validator --list
    python -m v2.stage3b_classification_review.validator --batch findings.md
    python -m v2.stage3b_classification_review.validator --suggest "Snacks > Chips"

Usage as module:
    from v2.stage3b_classification_review.validator import validate_label, suggest_correction
    
    is_valid, msg = validate_label("Carnes", "Jamón")  # True, "Valid"
    is_valid, msg = validate_label("Snacks", "Chips")  # False, "Invalid subcategory..."
    
    corrected = suggest_correction("Snacks", "Chips")  # "Snacks > Papas Fritas"
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

from v2.stage3_classification.taxonomy import TAXONOMY, is_valid, all_labels


# Common misspellings / wrong terms that agents might invent
# Maps lowercase wrong term -> (correct_category, correct_subcategory)
COMMON_MISTAKES = {
    # Snacks
    "chips": ("Snacks", "Papas Fritas"),
    "crisps": ("Snacks", "Papas Fritas"),
    "fries": ("Snacks", "Papas Fritas"),
    "nachos": ("Snacks", "Totopos"),
    "popcorn": ("Snacks", "Palomitas"),
    "nuts": ("Snacks", "Frutos Secos"),
    "crackers": ("Snacks", "Botanas"),
    # Bebidas
    "soda": ("Bebidas", "Refresco"),
    "soft drink": ("Bebidas", "Refresco"),
    "energy drink": ("Bebidas", "Refresco"),
    "juice": ("Bebidas", "Jugo"),
    "beer": ("Bebidas", "Cerveza"),
    "wine": ("Bebidas", "Vino"),
    "water": ("Bebidas", "Agua"),
    "coffee": ("Bebidas", "Café"),
    "tea": ("Bebidas", "Té"),
    "cocktail": ("Bebidas", "Cóctel"),
    "hot chocolate": ("Bebidas", "Chocolate"),
    # Carnes
    "chicken": ("Carnes", "Pollo"),
    "beef": ("Carnes", "Res"),
    "pork": ("Carnes", "Cerdo"),
    "fish": ("Carnes", "Pescado"),
    "tuna": ("Carnes", "Atún"),
    "ham": ("Carnes", "Jamón"),
    "bacon": ("Carnes", "Cerdo"),
    "sausage": ("Carnes", "Embutidos"),
    "ground meat": ("Carnes", "Carne Molida"),
    "minced meat": ("Carnes", "Carne Molida"),
    "steak": ("Carnes", "Res"),
    "vegetarian": ("Carnes", "Vegetariana"),
    # Dulces
    "candy": ("Dulces", "Golosinas"),
    "sweets": ("Dulces", "Golosinas"),
    "cookies": ("Dulces", "Galletas"),
    "biscuits": ("Dulces", "Galletas"),
    "chocolate": ("Dulces", "Chocolate"),
    "ice cream": ("Dulces", "Helado"),
    "cake": ("Dulces", "Pasteles"),
    "dessert": ("Dulces", "Postres"),
    "spread": ("Dulces", "Untables"),
    "cereal bar": ("Dulces", "Barritas"),
    "granola bar": ("Dulces", "Barritas"),
    # Lácteos
    "milk": ("Lácteos", "Leche"),
    "yogurt": ("Lácteos", "Yogur"),
    "yoghurt": ("Lácteos", "Yogur"),
    "cheese": ("Lácteos", "Queso"),
    "butter": ("Lácteos", "Mantequilla"),
    "cream": ("Lácteos", "Crema"),
    "eggs": ("Lácteos", "Huevos"),
    "egg": ("Lácteos", "Huevos"),
    "plant milk": ("Lácteos", "Leche Vegetal"),
    "oat milk": ("Lácteos", "Leche Vegetal"),
    "almond milk": ("Lácteos", "Leche Vegetal"),
    "skimmed milk": ("Lácteos", "Leche Deslactosada"),
    "skim milk": ("Lácteos", "Leche Deslactosada"),
    # Frutas & Verduras
    "apple": ("Frutas & Verduras", "Manzana"),
    "apples": ("Frutas & Verduras", "Manzana"),
    "banana": ("Frutas & Verduras", "Plátano"),
    "bananas": ("Frutas & Verduras", "Plátano"),
    "orange": ("Frutas & Verduras", "Naranja"),
    "oranges": ("Frutas & Verduras", "Naranja"),
    "lemon": ("Frutas & Verduras", "Limón"),
    "lime": ("Frutas & Verduras", "Limón"),
    "strawberry": ("Frutas & Verduras", "Fresa"),
    "strawberries": ("Frutas & Verduras", "Fresa"),
    "raspberry": ("Frutas & Verduras", "Frambuesa"),
    "raspberries": ("Frutas & Verduras", "Frambuesa"),
    "grape": ("Frutas & Verduras", "Uvas"),
    "grapes": ("Frutas & Verduras", "Uvas"),
    "watermelon": ("Frutas & Verduras", "Sandía"),
    "mango": ("Frutas & Verduras", "Mango"),
    "peach": ("Frutas & Verduras", "Frutas"),
    "pear": ("Frutas & Verduras", "Pera"),
    "pineapple": ("Frutas & Verduras", "Frutas"),
    "tomato": ("Frutas & Verduras", "Tomate"),
    "tomatoes": ("Frutas & Verduras", "Tomate"),
    "potato": ("Frutas & Verduras", "Papas"),
    "potatoes": ("Frutas & Verduras", "Papas"),
    "carrot": ("Frutas & Verduras", "Zanahoria"),
    "carrots": ("Frutas & Verduras", "Zanahoria"),
    "onion": ("Frutas & Verduras", "Cebolla"),
    "onions": ("Frutas & Verduras", "Cebolla"),
    "garlic": ("Frutas & Verduras", "Ajo"),
    "lettuce": ("Frutas & Verduras", "Lechuga"),
    "cucumber": ("Frutas & Verduras", "Pepino"),
    "pepper": ("Frutas & Verduras", "Pimiento"),
    "peppers": ("Frutas & Verduras", "Pimiento"),
    "broccoli": ("Frutas & Verduras", "Brócoli"),
    "spinach": ("Frutas & Verduras", "Espinaca"),
    "mushroom": ("Frutas & Verduras", "Champiñones"),
    "mushrooms": ("Frutas & Verduras", "Champiñones"),
    "corn": ("Frutas & Verduras", "Maíz"),
    "zucchini": ("Frutas & Verduras", "Calabacín"),
    "courgette": ("Frutas & Verduras", "Calabacín"),
    "avocado": ("Frutas & Verduras", "Frutas"),
    "berries": ("Frutas & Verduras", "Frutas"),
    "mixed vegetables": ("Frutas & Verduras", "Mezcla de Verduras"),
    "mixed veg": ("Frutas & Verduras", "Mezcla de Verduras"),
    "herbs": ("Frutas & Verduras", "Hierbas Frescas"),
    "fresh herbs": ("Frutas & Verduras", "Hierbas Frescas"),
    "dried fruit": ("Frutas & Verduras", "Fruta Seca"),
    "canned": ("Frutas & Verduras", "Conservas"),
    "frozen": ("Frutas & Verduras", "Conservas"),
    # Higiene
    "shampoo": ("Higiene", "Cuidado del Cabello"),
    "conditioner": ("Higiene", "Cuidado del Cabello"),
    "hair care": ("Higiene", "Cuidado del Cabello"),
    "soap": ("Higiene", "Jabón"),
    "body wash": ("Higiene", "Jabón"),
    "toothpaste": ("Higiene", "Dental"),
    "toothbrush": ("Higiene", "Dental"),
    "dental": ("Higiene", "Dental"),
    "razor": ("Higiene", "Afeitado"),
    "shaving": ("Higiene", "Afeitado"),
    "shaver": ("Higiene", "Afeitado"),
    "tissues": ("Higiene", "Pañuelos"),
    "kleenex": ("Higiene", "Pañuelos"),
    "toilet paper": ("Higiene", "Papel Higiénico"),
    "wipes": ("Higiene", "Toallitas"),
    "baby wipes": ("Higiene", "Toallitas"),
    "cotton": ("Higiene", "Algodón"),
    "cotton swabs": ("Higiene", "Algodón"),
    "cotton buds": ("Higiene", "Algodón"),
    "pads": ("Higiene", "Higiene Femenina"),
    "tampons": ("Higiene", "Higiene Femenina"),
    "menstrual": ("Higiene", "Higiene Femenina"),
    # Hogar
    "cleaning": ("Hogar", "Limpieza"),
    "cleaner": ("Hogar", "Limpieza"),
    "detergent": ("Hogar", "Lavandería"),
    "laundry": ("Hogar", "Lavandería"),
    "washing powder": ("Hogar", "Lavandería"),
    "bags": ("Hogar", "Bolsas"),
    "trash bags": ("Hogar", "Bolsas"),
    "garbage bags": ("Hogar", "Bolsas"),
    "shopping bag": ("Hogar", "Bolsas"),
    "aluminum foil": ("Hogar", "Utensilios de Cocina"),
    "aluminium foil": ("Hogar", "Utensilios de Cocina"),
    "plastic wrap": ("Hogar", "Utensilios de Cocina"),
    "cling film": ("Hogar", "Utensilios de Cocina"),
    "kitchen": ("Hogar", "Utensilios de Cocina"),
    "cookware": ("Hogar", "Utensilios de Cocina"),
    "utensils": ("Hogar", "Utensilios de Cocina"),
    "batteries": ("Hogar", "Baterías"),
    "battery": ("Hogar", "Baterías"),
    "light bulbs": ("Hogar", "Baterías"),
    "air freshener": ("Hogar", "Ambientador"),
    "candles": ("Hogar", "Ambientador"),
    "candle": ("Hogar", "Ambientador"),
    "oil": ("Hogar", "Aceite y Vinagre"),
    "olive oil": ("Hogar", "Aceite y Vinagre"),
    "vinegar": ("Hogar", "Aceite y Vinagre"),
    "sauce": ("Hogar", "Salsas"),
    "ketchup": ("Hogar", "Salsas"),
    "mustard": ("Hogar", "Salsas"),
    "mayonnaise": ("Hogar", "Salsas"),
    "spices": ("Hogar", "Condimentos"),
    "seasoning": ("Hogar", "Condimentos"),
    "salt": ("Hogar", "Condimentos"),
    "pepper": ("Hogar", "Condimentos"),
    "sugar": ("Hogar", "Condimentos"),
    "flour": ("Hogar", "Harina"),
    "beans": ("Hogar", "Frijoles"),
    "canned beans": ("Hogar", "Frijoles"),
    "black beans": ("Hogar", "Frijoles"),
    "jam": ("Hogar", "Mermeladas"),
    "marmalade": ("Hogar", "Mermeladas"),
    "honey": ("Hogar", "Mermeladas"),
    "paper": ("Hogar", "Papelería"),
    "notebook": ("Hogar", "Papelería"),
    "pen": ("Hogar", "Papelería"),
    "pet food": ("Hogar", "Mascotas"),
    "cat food": ("Hogar", "Mascotas"),
    "dog food": ("Hogar", "Mascotas"),
    "cat litter": ("Hogar", "Mascotas"),
    "decoration": ("Hogar", "Decoración"),
    "decor": ("Hogar", "Decoración"),
    "plant": ("Hogar", "Jardinería"),
    "plants": ("Hogar", "Jardinería"),
    "garden": ("Hogar", "Jardinería"),
    "flowers": ("Hogar", "Jardinería"),
    "disposable": ("Hogar", "Desechables"),
    "plates": ("Hogar", "Desechables"),
    "cups": ("Hogar", "Desechables"),
    "napkins": ("Hogar", "Desechables"),
    "cutlery": ("Hogar", "Desechables"),
    "cereal": ("Hogar", "Cereal"),
    "muesli": ("Hogar", "Cereal"),
    "granola": ("Hogar", "Cereal"),
    # Panadería
    "bread": ("Panadería", "Pan"),
    "baguette": ("Panadería", "Pan"),
    "roll": ("Panadería", "Pan"),
    "bun": ("Panadería", "Pan"),
    "loaf": ("Panadería", "Pan"),
    "croissant": ("Panadería", "Pan Dulce"),
    "donut": ("Panadería", "Pan Dulce"),
    "doughnut": ("Panadería", "Pan Dulce"),
    "muffin": ("Panadería", "Pan Dulce"),
    "sweet bread": ("Panadería", "Pan Dulce"),
    "pastry": ("Panadería", "Repostería"),
    "cake": ("Panadería", "Repostería"),
    "tart": ("Panadería", "Repostería"),
    "pie": ("Panadería", "Repostería"),
    "tortilla": ("Panadería", "Tortilla"),
    "wrap": ("Panadería", "Tortilla"),
    "focaccia": ("Panadería", "Focaccia"),
    "hamburger bun": ("Panadería", "Pan Hamburguesa"),
    "burger bun": ("Panadería", "Pan Hamburguesa"),
    "hotdog bun": ("Panadería", "Pan para Hotdog"),
    "hot dog bun": ("Panadería", "Pan para Hotdog"),
    # Pasta/Sopas
    "pasta": ("Pasta/Sopas", "Pasta"),
    "spaghetti": ("Pasta/Sopas", "Pasta"),
    "penne": ("Pasta/Sopas", "Pasta"),
    "fusilli": ("Pasta/Sopas", "Pasta"),
    "noodles": ("Pasta/Sopas", "Pasta"),
    "macaroni": ("Pasta/Sopas", "Pasta"),
    "rice": ("Pasta/Sopas", "Arroz"),
    "soup": ("Pasta/Sopas", "Sopas"),
    "ramen": ("Pasta/Sopas", "Fideos Instantáneos"),
    "instant noodles": ("Pasta/Sopas", "Fideos Instantáneos"),
    "ravioli": ("Pasta/Sopas", "Pasta Rellena"),
    "dumpling": ("Pasta/Sopas", "Pasta Rellena"),
    "dumplings": ("Pasta/Sopas", "Pasta Rellena"),
    "tortellini": ("Pasta/Sopas", "Pasta Rellena"),
    "lasagna": ("Pasta/Sopas", "Pasta Preparada"),
    "lasagne": ("Pasta/Sopas", "Pasta Preparada"),
    "pizza": ("Pasta/Sopas", "Pasta Preparada"),
    "grain": ("Pasta/Sopas", "Granos"),
    "grains": ("Pasta/Sopas", "Granos"),
    "couscous": ("Pasta/Sopas", "Granos"),
    "quinoa": ("Pasta/Sopas", "Granos"),
    # Salud
    "medicine": ("Salud", "Medicamentos"),
    "medication": ("Salud", "Medicamentos"),
    "pills": ("Salud", "Medicamentos"),
    "tablets": ("Salud", "Medicamentos"),
    "vitamins": ("Salud", "Suplementos"),
    "supplement": ("Salud", "Suplementos"),
    "protein": ("Salud", "Suplementos"),
    "protein powder": ("Salud", "Suplementos"),
}


def validate_label(category: str, subcategory: str) -> Tuple[bool, str]:
    """
    Validate a category/subcategory pair against the frozen taxonomy.
    
    Returns:
        (is_valid, message)
    """
    category = category.strip()
    subcategory = subcategory.strip()
    
    if category not in TAXONOMY:
        valid_cats = ", ".join(TAXONOMY.keys())
        return False, f"Invalid category '{category}'. Valid categories: {valid_cats}"
    
    if not is_valid(category, subcategory):
        valid_subs = ", ".join(TAXONOMY[category])
        return False, f"Invalid subcategory '{subcategory}' for '{category}'. Valid: {valid_subs}"
    
    return True, "Valid"


def suggest_correction(category: str, subcategory: str) -> str:
    """
    Suggest a valid correction for an invalid label.
    
    Returns a valid "Category > Subcategory" string, or a message if no good match.
    """
    category = category.strip()
    subcategory = subcategory.strip()
    
    # Check if category is valid
    if category not in TAXONOMY:
        # Try to find the category from common mistakes
        sub_lower = subcategory.lower()
        for wrong, (correct_cat, correct_sub) in COMMON_MISTAKES.items():
            if wrong in sub_lower or sub_lower in wrong:
                return f"{correct_cat} > {correct_sub}"
        return f"NEEDS TAXONOMY UPDATE: invalid category '{category}'"
    
    # Category is valid, check subcategory
    if is_valid(category, subcategory):
        return f"{category} > {subcategory}"
    
    # Try to find a match from common mistakes
    sub_lower = subcategory.lower()
    for wrong, (correct_cat, correct_sub) in COMMON_MISTAKES.items():
        if wrong in sub_lower or sub_lower in wrong:
            if correct_cat == category or correct_cat in TAXONOMY:
                return f"{correct_cat} > {correct_sub}"
    
    # Suggest Otros as fallback
    return f"{category} > Otros"


def validate_label_string(label: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validate a "Category > Subcategory" string.
    
    Returns:
        (is_valid, message, corrected_label)
    """
    label = label.strip()
    
    if label.startswith("NEEDS TAXONOMY UPDATE"):
        return True, "Marked for taxonomy update", label
    
    if "(keep)" in label.lower() or label.lower() in ["keep", "no change", "correct", "n/a"]:
        return True, "No change needed", label
    
    # Parse "Category > Subcategory"
    match = re.match(r'^(.+?)\s*>\s*(.+)$', label)
    if not match:
        return False, f"Could not parse label format: '{label}'. Expected 'Category > Subcategory'", None
    
    category, subcategory = match.group(1).strip(), match.group(2).strip()
    is_valid_result, msg = validate_label(category, subcategory)
    
    if is_valid_result:
        return True, msg, label
    
    corrected = suggest_correction(category, subcategory)
    return False, msg, corrected


def list_taxonomy():
    """Print the full taxonomy."""
    print(f"TAXONOMY ({len(all_labels())} valid pairs)\n")
    for category, subcategories in TAXONOMY.items():
        print(f"{category} ({len(subcategories)}):")
        for sub in subcategories:
            print(f"  - {category} > {sub}")
        print()


def validate_batch_file(filepath: str) -> int:
    """Validate all suggestions in a markdown findings file."""
    path = Path(filepath)
    if not path.exists():
        print(f"File not found: {filepath}")
        return 1
    
    valid_count = 0
    invalid_count = 0
    taxonomy_update_count = 0
    
    for line_num, line in enumerate(path.read_text().splitlines(), 1):
        if not line.startswith("|") or "Suggested Fix" in line or "---" in line:
            continue
        
        # Parse table row: | Item | Current | Issue | Suggested | Confidence |
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        
        item, current, issue, suggested, confidence = parts[1:6]
        is_valid_result, msg, corrected = validate_label_string(suggested)
        
        if is_valid_result:
            valid_count += 1
            if "taxonomy update" in msg.lower():
                taxonomy_update_count += 1
                print(f"[TAXONOMY UPDATE] Line {line_num}: {item} -> {suggested}")
        else:
            invalid_count += 1
            print(f"[INVALID] Line {line_num}: {item}")
            print(f"   Invalid: {suggested}")
            print(f"   Reason: {msg}")
            print(f"   Suggested correction: {corrected}")
    
    print(f"\n{'='*60}")
    print(f"Validation complete:")
    print(f"  Valid: {valid_count}")
    print(f"  Invalid (invented taxonomy): {invalid_count}")
    print(f"  Needs taxonomy update: {taxonomy_update_count}")
    print(f"{'='*60}")
    
    if invalid_count > 0:
        print("\n[WARNING] Workers invented sub-categories. Corrections suggested above.")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate classification labels against frozen taxonomy"
    )
    parser.add_argument("category", nargs="?", help="Category to validate")
    parser.add_argument("subcategory", nargs="?", help="Subcategory to validate")
    parser.add_argument("--list", action="store_true", help="List full taxonomy")
    parser.add_argument("--batch", help="Validate a markdown findings file")
    parser.add_argument("--suggest", help="Suggest correction for 'Category > Subcategory'")
    
    args = parser.parse_args()
    
    if args.list:
        list_taxonomy()
        return 0
    
    if args.batch:
        return validate_batch_file(args.batch)
    
    if args.suggest:
        is_valid_result, msg, corrected = validate_label_string(args.suggest)
        print(f"Input: {args.suggest}")
        print(f"Valid: {is_valid_result}")
        print(f"Message: {msg}")
        if corrected and corrected != args.suggest:
            print(f"Corrected: {corrected}")
        return 0 if is_valid_result else 1
    
    if args.category and args.subcategory:
        is_valid_result, msg = validate_label(args.category, args.subcategory)
        print(f"{args.category} > {args.subcategory}")
        print(f"Valid: {is_valid_result}")
        print(f"Message: {msg}")
        
        if not is_valid_result:
            corrected = suggest_correction(args.category, args.subcategory)
            print(f"Suggested correction: {corrected}")
        return 0 if is_valid_result else 1
    
    if args.category or args.subcategory:
        parser.print_help()
        return 1
    
    # Interactive mode
    print(f"Label Validator - Taxonomy ({len(all_labels())} valid pairs)")
    print("Type 'list' to see all valid labels, 'quit' to exit\n")
    
    while True:
        try:
            user_input = input("Enter 'Category > Subcategory': ").strip()
            if user_input.lower() in ["quit", "exit", "q"]:
                break
            if user_input.lower() == "list":
                list_taxonomy()
                continue
            
            is_valid_result, msg, corrected = validate_label_string(user_input)
            print(f"  Valid: {is_valid_result}")
            print(f"  {msg}")
            if corrected and corrected != user_input:
                print(f"  Suggested: {corrected}")
            print()
        except (KeyboardInterrupt, EOFError):
            break
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
