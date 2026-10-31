"""
Frozen category/subcategory taxonomy for stage 3.

TAXONOMY is the only set of labels the classifier may output.
SUBCATEGORY_ALIASES maps the (category, subcategory) pairs used in old_data.csv
onto the canonical taxonomy (dedupes Yogur/Yogurt, Fresa/Fresas, ... and moves
items that were filed under the wrong category).

Pairs that are already canonical don't need an alias.
"""

from typing import Dict, List, Optional, Tuple


OTHER = "Otros"

TAXONOMY: Dict[str, List[str]] = {
    "Bebidas": [
        "Agua", "Café", "Cerveza", "Chocolate", "Cóctel", "Jugo", "Refresco", "Té", "Vino", OTHER,
    ],
    "Carnes": [
        "Atún", "Carne Molida", "Cerdo", "Embutidos", "Jamón", "Pescado", "Pollo", "Res",
        "Vegetariana", OTHER,
    ],
    "Dulces": [
        "Barritas", "Chocolate", "Galletas", "Golosinas", "Helado", "Pasteles", "Postres",
        "Untables", OTHER,
    ],
    "Frutas & Verduras": [
        "Ajo", "Brócoli", "Brotes", "Calabacín", "Cebolla", "Champiñones", "Conservas", "Ejotes",
        "Espinaca", "Frambuesa", "Fresa", "Fruta Seca", "Frutas", "Hierbas Frescas", "Lechuga",
        "Limón", "Maíz", "Mandarina", "Mango", "Manzana", "Mezcla de Verduras", "Naranja",
        "Papas", "Pepino", "Pera", "Pimiento", "Plátano", "Sandía", "Tomate", "Uvas", "Verduras",
        "Zanahoria", OTHER,
    ],
    "Higiene": [
        "Afeitado", "Algodón", "Cuidado del Cabello", "Dental", "Higiene Femenina", "Jabón",
        "Pañuelos", "Papel Higiénico", "Toallitas", OTHER,
    ],
    "Hogar": [
        "Aceite y Vinagre", "Ambientador", "Baterías", "Bolsas", "Cereal", "Condimentos",
        "Conservas", "Decoración", "Desechables", "Frijoles", "Harina", "Jardinería",
        "Lavandería", "Limpieza", "Mascotas", "Mermeladas", "Papelería", "Salsas",
        "Utensilios de Cocina", OTHER,
    ],
    "Lácteos": [
        "Crema", "Huevos", "Leche", "Leche Deslactosada", "Leche Vegetal", "Mantequilla",
        "Queso", "Yogur", OTHER,
    ],
    "Panadería": [
        "Focaccia", "Pan", "Pan Dulce", "Pan Hamburguesa", "Pan para Hotdog", "Repostería",
        "Tortilla", OTHER,
    ],
    "Pasta/Sopas": [
        "Arroz", "Fideos Instantáneos", "Granos", "Pasta", "Pasta Preparada", "Pasta Rellena",
        "Sopas", OTHER,
    ],
    "Salud": ["Medicamentos", "Suplementos", OTHER],
    "Snacks": [
        "Botanas", "Dips", "Frutos Secos", "Palomitas", "Papas Fritas", "Totopos", OTHER,
    ],
}

# (old category, old subcategory) -> (canonical category, canonical subcategory)
SUBCATEGORY_ALIASES: Dict[Tuple[str, str], Tuple[str, str]] = {
    # Bebidas
    ("Bebidas", "Bebida"): ("Lácteos", "Leche Vegetal"),
    ("Bebidas", "Leche Saborizada"): ("Bebidas", "Chocolate"),
    # Carnes
    ("Carnes", "Vegana"): ("Carnes", "Vegetariana"),
    # Dulces
    ("Dulces", "Pastel"): ("Dulces", "Pasteles"),
    ("Dulces", "Pastelillos"): ("Dulces", "Pasteles"),
    ("Dulces", "Postre Holandés"): ("Dulces", "Postres"),
    # Frutas & Verduras
    ("Frutas & Verduras", "Fresas"): ("Frutas & Verduras", "Fresa"),
    ("Frutas & Verduras", "Germinados"): ("Frutas & Verduras", "Brotes"),
    ("Frutas & Verduras", "Naranjas"): ("Frutas & Verduras", "Naranja"),
    ("Frutas & Verduras", "Mezcla"): ("Frutas & Verduras", "Mezcla de Verduras"),
    ("Frutas & Verduras", "Mezclas"): ("Frutas & Verduras", "Mezcla de Verduras"),
    ("Frutas & Verduras", "Verdura Mixta"): ("Frutas & Verduras", "Mezcla de Verduras"),
    ("Frutas & Verduras", "Verduras Mixtas"): ("Frutas & Verduras", "Mezcla de Verduras"),
    ("Frutas & Verduras", "Verduras Variadas"): ("Frutas & Verduras", "Mezcla de Verduras"),
    ("Frutas & Verduras", "Vegetales"): ("Frutas & Verduras", "Verduras"),
    # Higiene
    ("Higiene", "Afeitadora"): ("Higiene", "Afeitado"),
    ("Higiene", "Personal"): ("Higiene", "Afeitado"),
    ("Higiene", "Bastoncillos"): ("Higiene", "Algodón"),
    ("Higiene", "Shampoo"): ("Higiene", "Cuidado del Cabello"),
    ("Higiene", "Higiene Personal"): ("Higiene", "Cuidado del Cabello"),
    ("Higiene", "Toallas Femeninas"): ("Higiene", "Higiene Femenina"),
    ("Higiene", "Kleenex"): ("Higiene", "Pañuelos"),
    # Hogar
    ("Hogar", "Aceite"): ("Hogar", "Aceite y Vinagre"),
    ("Hogar", "Vinagre"): ("Hogar", "Aceite y Vinagre"),
    ("Hogar", "Arroz"): ("Pasta/Sopas", "Arroz"),
    ("Hogar", "Pilas"): ("Hogar", "Baterías"),
    ("Hogar", "Cereales"): ("Hogar", "Cereal"),
    ("Hogar", "Chocolate"): ("Dulces", "Chocolate"),
    ("Hogar", "Cocina"): ("Hogar", "Utensilios de Cocina"),
    ("Hogar", "Utensilios"): ("Hogar", "Utensilios de Cocina"),
    ("Hogar", "Especias"): ("Hogar", "Condimentos"),
    ("Hogar", "Sal"): ("Hogar", "Condimentos"),
    ("Hogar", "Sazonador"): ("Hogar", "Condimentos"),
    ("Hogar", "Enlatados/Pescado"): ("Carnes", "Atún"),
    ("Hogar", "Fruta Seca"): ("Frutas & Verduras", "Fruta Seca"),
    ("Hogar", "Helado"): ("Dulces", "Helado"),
    ("Hogar", "Postres"): ("Dulces", "Postres"),
    ("Hogar", "Untables"): ("Dulces", "Untables"),
    ("Hogar", "Higiene Personal"): ("Hogar", "Limpieza"),
    ("Hogar", "Huevos"): ("Lácteos", "Huevos"),
    ("Hogar", "Papas"): ("Frutas & Verduras", "Papas"),
    ("Hogar", "Papas Preparadas"): ("Frutas & Verduras", "Papas"),
    ("Hogar", "Papel Higiénico"): ("Higiene", "Papel Higiénico"),
    ("Hogar", "Pañuelos"): ("Higiene", "Pañuelos"),
    ("Hogar", "Salsa"): ("Hogar", "Salsas"),
    ("Hogar", "Salsa de Pasta"): ("Hogar", "Salsas"),
    ("Hogar", "Salsa para Pasta"): ("Hogar", "Salsas"),
    ("Hogar", "Servilletas"): ("Hogar", "Desechables"),
    ("Hogar", "Toallas de Cocina"): ("Hogar", "Desechables"),
    ("Hogar", "Utensilios de Mesa"): ("Hogar", "Desechables"),
    ("Hogar", "Snack Salado"): ("Snacks", "Botanas"),
    ("Hogar", "Sopa"): ("Pasta/Sopas", "Sopas"),
    ("Hogar", "Tortilla"): ("Panadería", "Tortilla"),
    # Lácteos
    ("Lácteos", "Leche con Chocolate"): ("Bebidas", "Chocolate"),
    ("Lácteos", "Leche de Avena"): ("Lácteos", "Leche Vegetal"),
    ("Lácteos", "Quesos"): ("Lácteos", "Queso"),
    ("Lácteos", "Yogurt"): ("Lácteos", "Yogur"),
    # Panadería
    ("Panadería", "Pan Blanco"): ("Panadería", "Pan"),
    ("Panadería", "Pan Integral"): ("Panadería", "Pan"),
    ("Panadería", "Pan de Caja"): ("Panadería", "Pan"),
    ("Panadería", "Postres"): ("Panadería", "Repostería"),
    # Pasta/Sopas
    ("Pasta/Sopas", "Caldo/Sopa"): ("Pasta/Sopas", "Sopas"),
    ("Pasta/Sopas", "Pasta Larga"): ("Pasta/Sopas", "Pasta"),
    ("Pasta/Sopas", "Penne"): ("Pasta/Sopas", "Pasta"),
    ("Pasta/Sopas", "Tagliatelle"): ("Pasta/Sopas", "Pasta"),
    ("Pasta/Sopas", "Ravioli"): ("Pasta/Sopas", "Pasta Rellena"),
    ("Pasta/Sopas", "Ramen"): ("Pasta/Sopas", "Fideos Instantáneos"),
    ("Pasta/Sopas", "Sopa Instantánea"): ("Pasta/Sopas", "Fideos Instantáneos"),
    # Salud
    ("Salud", "Vegana"): ("Carnes", "Vegetariana"),
    # Snacks
    ("Snacks", "Chocolate"): ("Dulces", "Chocolate"),
    ("Snacks", "Dulces"): ("Dulces", "Golosinas"),
    ("Snacks", "Galletas"): ("Dulces", "Galletas"),
    ("Snacks", "Helado"): ("Dulces", "Helado"),
    ("Snacks", "Nachos"): ("Snacks", "Totopos"),
    ("Snacks", "Salsas"): ("Snacks", "Dips"),
    ("Snacks", "Untables"): ("Snacks", "Dips"),
}

LABEL_SEP = " > "


def is_valid(category: str, subcategory: str) -> bool:
    """True if (category, subcategory) is in the frozen taxonomy."""
    return subcategory in TAXONOMY.get(category, [])


def canonicalize(category: str, subcategory: str) -> Optional[Tuple[str, str]]:
    """
    Map an old (category, subcategory) pair onto the taxonomy.

    Returns None if the pair is neither canonical nor aliased.
    """
    category, subcategory = category.strip(), subcategory.strip()
    if is_valid(category, subcategory):
        return category, subcategory
    return SUBCATEGORY_ALIASES.get((category, subcategory))


def all_labels() -> List[str]:
    """Flat list of 'Category > Subcategory' strings (used as the LLM enum)."""
    return [f"{c}{LABEL_SEP}{s}" for c, subs in TAXONOMY.items() for s in subs]


def split_label(label: str) -> Tuple[str, str]:
    """'Category > Subcategory' -> (category, subcategory)."""
    category, subcategory = label.split(LABEL_SEP, 1)
    return category, subcategory
