"""
Seed for the v2 taxonomy and the v1 -> v2 map (from PROPOSAL.md).

V2_TAXONOMY is loaded into the category / subcategory tables by `cli init`.
After that the tables are the source of truth; edit them with the CLI, not here.

V1_MAP covers every (category, subcategory) of the v1 taxonomy
(v2.stage3_classification.taxonomy.TAXONOMY):
- a single "Category > Subcategory" string: every product moves there (sync source=map)
- a list of them: the products are split, the LLM picks one per product (source=split_llm)
"""

from typing import Dict, List, Tuple, Union


V2_TAXONOMY: Dict[str, List[str]] = {
    "Bebidas": [
        "Agua", "Bebidas de Chocolate", "Cerveza", "Jugo", "Refresco", "Té y Café",
        "Vino y Cócteles", "Otros",
    ],
    "Carnes y Pescado": [
        "Carne Molida", "Cerdo", "Embutidos y Fiambres", "Hamburguesas y Albóndigas", "Jamón",
        "Pescado y Mariscos", "Pollo", "Res", "Otros",
    ],
    "Frutas": [
        "Bayas", "Cítricos", "Frutas Tropicales", "Manzana", "Plátano", "Otros",
    ],
    "Verduras": [
        "Brócoli y Coliflor", "Cebolla y Ajo", "Lechuga y Ensaladas", "Maíz",
        "Mezclas de Verduras", "Papas", "Pepino y Calabacín", "Pimientos y Chiles", "Tomate",
        "Verduras Snack", "Zanahoria", "Otros",
    ],
    "Lácteos y Huevos": [
        "Crema", "Huevos", "Leche", "Leche Deslactosada", "Leche Vegetal", "Mantequilla",
        "Mozzarella", "Queso Fresco y Crema", "Queso Italiano y Feta", "Queso Madurado",
        "Queso Rallado", "Yogur", "Otros",
    ],
    "Panadería": [
        "Baguette", "Focaccia", "Hotcakes y Repostería", "Pan de Molde y Barra", "Pan Dulce",
        "Pan para Hamburguesa y Hotdog", "Panecillos", "Tortilla", "Otros",
    ],
    "Despensa": [
        "Aceite y Vinagre", "Aderezos", "Arroz y Granos", "Caldos y Sazonadores",
        "Cereales y Avena", "Conservas y Legumbres", "Fideos Instantáneos",
        "Frutos Secos y Fruta Seca", "Harina y Repostería", "Mermeladas y Untables", "Pasta",
        "Pasta Rellena", "Sal y Especias", "Salsas del Mundo", "Salsas para Pasta", "Sopas",
        "Otros",
    ],
    "Dulces": [
        "Chocolate", "Galletas y Pasteles", "Golosinas", "Helado", "Postres", "Otros",
    ],
    "Snacks": [
        "Botanas y Palomitas", "Dips", "Papas Fritas", "Totopos", "Otros",
    ],
    "Comida Preparada": [
        "Platos Preparados", "Otros",
    ],
    "Cuidado Personal y Salud": [
        "Afeitado y Cuidado", "Cuidado del Cabello", "Dental", "Higiene Femenina", "Jabón",
        "Medicamentos", "Pañuelos", "Papel Higiénico", "Toallitas", "Otros",
    ],
    "Limpieza y Lavandería": [
        "Ambientador", "Lavandería", "Lavavajillas y Platos", "Limpiadores", "Otros",
    ],
    "Hogar": [
        "Baterías", "Bolsas de Basura", "Bolsas Reutilizables", "Desechables de Cocina",
        "Mascotas", "Papelería", "Utensilios de Cocina", "Otros",
    ],
}

Target = Union[str, List[str]]

V1_MAP: Dict[Tuple[str, str], Target] = {
    # Bebidas
    ("Bebidas", "Agua"): "Bebidas > Agua",
    ("Bebidas", "Café"): "Bebidas > Té y Café",
    ("Bebidas", "Cerveza"): "Bebidas > Cerveza",
    ("Bebidas", "Chocolate"): "Bebidas > Bebidas de Chocolate",
    ("Bebidas", "Cóctel"): "Bebidas > Vino y Cócteles",
    ("Bebidas", "Jugo"): "Bebidas > Jugo",
    ("Bebidas", "Refresco"): "Bebidas > Refresco",
    ("Bebidas", "Té"): "Bebidas > Té y Café",
    ("Bebidas", "Vino"): "Bebidas > Vino y Cócteles",
    ("Bebidas", "Otros"): "Bebidas > Otros",
    # Carnes
    ("Carnes", "Atún"): "Carnes y Pescado > Pescado y Mariscos",
    ("Carnes", "Carne Molida"): "Carnes y Pescado > Carne Molida",
    ("Carnes", "Cerdo"): "Carnes y Pescado > Cerdo",
    ("Carnes", "Embutidos"): "Carnes y Pescado > Embutidos y Fiambres",
    ("Carnes", "Jamón"): "Carnes y Pescado > Jamón",
    ("Carnes", "Pescado"): "Carnes y Pescado > Pescado y Mariscos",
    ("Carnes", "Pollo"): [
        "Carnes y Pescado > Pollo", "Carnes y Pescado > Carne Molida",
        "Carnes y Pescado > Hamburguesas y Albóndigas", "Comida Preparada > Platos Preparados",
    ],
    ("Carnes", "Res"): [
        "Carnes y Pescado > Res", "Carnes y Pescado > Carne Molida",
        "Carnes y Pescado > Hamburguesas y Albóndigas",
    ],
    ("Carnes", "Vegetariana"): "Carnes y Pescado > Otros",
    ("Carnes", "Otros"): "Carnes y Pescado > Otros",
    # Dulces
    ("Dulces", "Barritas"): "Dulces > Galletas y Pasteles",
    ("Dulces", "Chocolate"): "Dulces > Chocolate",
    ("Dulces", "Galletas"): "Dulces > Galletas y Pasteles",
    ("Dulces", "Golosinas"): "Dulces > Golosinas",
    ("Dulces", "Helado"): "Dulces > Helado",
    ("Dulces", "Pasteles"): "Dulces > Galletas y Pasteles",
    ("Dulces", "Postres"): ["Dulces > Postres", "Panadería > Hotcakes y Repostería"],
    ("Dulces", "Untables"): "Despensa > Mermeladas y Untables",
    ("Dulces", "Otros"): "Dulces > Otros",
    # Frutas & Verduras
    ("Frutas & Verduras", "Ajo"): "Verduras > Cebolla y Ajo",
    ("Frutas & Verduras", "Brócoli"): "Verduras > Brócoli y Coliflor",
    ("Frutas & Verduras", "Brotes"): "Verduras > Otros",
    ("Frutas & Verduras", "Calabacín"): "Verduras > Pepino y Calabacín",
    ("Frutas & Verduras", "Cebolla"): "Verduras > Cebolla y Ajo",
    ("Frutas & Verduras", "Champiñones"): "Verduras > Otros",
    ("Frutas & Verduras", "Conservas"): "Despensa > Conservas y Legumbres",
    ("Frutas & Verduras", "Ejotes"): "Verduras > Otros",
    ("Frutas & Verduras", "Espinaca"): "Verduras > Lechuga y Ensaladas",
    ("Frutas & Verduras", "Frambuesa"): "Frutas > Bayas",
    ("Frutas & Verduras", "Fresa"): "Frutas > Bayas",
    ("Frutas & Verduras", "Fruta Seca"): "Despensa > Frutos Secos y Fruta Seca",
    ("Frutas & Verduras", "Frutas"): [
        "Frutas > Bayas", "Frutas > Cítricos", "Frutas > Frutas Tropicales", "Frutas > Otros",
    ],
    ("Frutas & Verduras", "Hierbas Frescas"): "Verduras > Otros",
    ("Frutas & Verduras", "Lechuga"): "Verduras > Lechuga y Ensaladas",
    ("Frutas & Verduras", "Limón"): "Frutas > Cítricos",
    ("Frutas & Verduras", "Maíz"): "Verduras > Maíz",
    ("Frutas & Verduras", "Mandarina"): "Frutas > Cítricos",
    ("Frutas & Verduras", "Mango"): "Frutas > Frutas Tropicales",
    ("Frutas & Verduras", "Manzana"): "Frutas > Manzana",
    ("Frutas & Verduras", "Mezcla de Verduras"): [
        "Verduras > Lechuga y Ensaladas", "Verduras > Mezclas de Verduras",
        "Verduras > Verduras Snack", "Verduras > Brócoli y Coliflor",
    ],
    ("Frutas & Verduras", "Naranja"): "Frutas > Cítricos",
    ("Frutas & Verduras", "Papas"): "Verduras > Papas",
    ("Frutas & Verduras", "Pepino"): "Verduras > Pepino y Calabacín",
    ("Frutas & Verduras", "Pera"): "Frutas > Otros",
    ("Frutas & Verduras", "Pimiento"): "Verduras > Pimientos y Chiles",
    ("Frutas & Verduras", "Plátano"): "Frutas > Plátano",
    ("Frutas & Verduras", "Sandía"): "Frutas > Otros",
    ("Frutas & Verduras", "Tomate"): "Verduras > Tomate",
    ("Frutas & Verduras", "Uvas"): "Frutas > Otros",
    ("Frutas & Verduras", "Verduras"): [
        "Verduras > Mezclas de Verduras", "Verduras > Verduras Snack",
        "Verduras > Brócoli y Coliflor", "Verduras > Pimientos y Chiles", "Verduras > Otros",
    ],
    ("Frutas & Verduras", "Zanahoria"): "Verduras > Zanahoria",
    ("Frutas & Verduras", "Otros"): "Verduras > Otros",
    # Higiene
    ("Higiene", "Afeitado"): "Cuidado Personal y Salud > Afeitado y Cuidado",
    ("Higiene", "Algodón"): "Cuidado Personal y Salud > Afeitado y Cuidado",
    ("Higiene", "Cuidado del Cabello"): "Cuidado Personal y Salud > Cuidado del Cabello",
    ("Higiene", "Dental"): "Cuidado Personal y Salud > Dental",
    ("Higiene", "Higiene Femenina"): "Cuidado Personal y Salud > Higiene Femenina",
    ("Higiene", "Jabón"): "Cuidado Personal y Salud > Jabón",
    ("Higiene", "Pañuelos"): "Cuidado Personal y Salud > Pañuelos",
    ("Higiene", "Papel Higiénico"): "Cuidado Personal y Salud > Papel Higiénico",
    ("Higiene", "Toallitas"): "Cuidado Personal y Salud > Toallitas",
    ("Higiene", "Otros"): "Cuidado Personal y Salud > Otros",
    # Hogar
    ("Hogar", "Aceite y Vinagre"): "Despensa > Aceite y Vinagre",
    ("Hogar", "Ambientador"): "Limpieza y Lavandería > Ambientador",
    ("Hogar", "Baterías"): "Hogar > Baterías",
    ("Hogar", "Bolsas"): ["Hogar > Bolsas de Basura", "Hogar > Bolsas Reutilizables"],
    ("Hogar", "Cereal"): "Despensa > Cereales y Avena",
    ("Hogar", "Condimentos"): [
        "Despensa > Sal y Especias", "Despensa > Caldos y Sazonadores",
        "Despensa > Harina y Repostería", "Despensa > Frutos Secos y Fruta Seca",
    ],
    ("Hogar", "Conservas"): "Despensa > Conservas y Legumbres",
    ("Hogar", "Decoración"): "Hogar > Otros",
    ("Hogar", "Desechables"): "Hogar > Desechables de Cocina",
    ("Hogar", "Frijoles"): "Despensa > Conservas y Legumbres",
    ("Hogar", "Harina"): "Despensa > Harina y Repostería",
    ("Hogar", "Jardinería"): "Hogar > Otros",
    ("Hogar", "Lavandería"): "Limpieza y Lavandería > Lavandería",
    ("Hogar", "Limpieza"): [
        "Limpieza y Lavandería > Lavavajillas y Platos", "Limpieza y Lavandería > Limpiadores",
        "Limpieza y Lavandería > Lavandería",
    ],
    ("Hogar", "Mascotas"): "Hogar > Mascotas",
    ("Hogar", "Mermeladas"): "Despensa > Mermeladas y Untables",
    ("Hogar", "Papelería"): "Hogar > Papelería",
    ("Hogar", "Salsas"): [
        "Despensa > Salsas para Pasta", "Despensa > Aderezos", "Despensa > Salsas del Mundo",
    ],
    ("Hogar", "Utensilios de Cocina"): "Hogar > Utensilios de Cocina",
    ("Hogar", "Otros"): "Hogar > Otros",
    # Lácteos
    ("Lácteos", "Crema"): "Lácteos y Huevos > Crema",
    ("Lácteos", "Huevos"): "Lácteos y Huevos > Huevos",
    ("Lácteos", "Leche"): "Lácteos y Huevos > Leche",
    ("Lácteos", "Leche Deslactosada"): "Lácteos y Huevos > Leche Deslactosada",
    ("Lácteos", "Leche Vegetal"): "Lácteos y Huevos > Leche Vegetal",
    ("Lácteos", "Mantequilla"): "Lácteos y Huevos > Mantequilla",
    ("Lácteos", "Queso"): [
        "Lácteos y Huevos > Queso Madurado", "Lácteos y Huevos > Queso Rallado",
        "Lácteos y Huevos > Queso Fresco y Crema", "Lácteos y Huevos > Mozzarella",
        "Lácteos y Huevos > Queso Italiano y Feta",
    ],
    ("Lácteos", "Yogur"): "Lácteos y Huevos > Yogur",
    ("Lácteos", "Otros"): "Lácteos y Huevos > Otros",
    # Panadería
    ("Panadería", "Focaccia"): "Panadería > Focaccia",
    ("Panadería", "Pan"): [
        "Panadería > Pan de Molde y Barra", "Panadería > Panecillos", "Panadería > Baguette",
    ],
    ("Panadería", "Pan Dulce"): "Panadería > Pan Dulce",
    ("Panadería", "Pan Hamburguesa"): "Panadería > Pan para Hamburguesa y Hotdog",
    ("Panadería", "Pan para Hotdog"): "Panadería > Pan para Hamburguesa y Hotdog",
    ("Panadería", "Repostería"): "Panadería > Hotcakes y Repostería",
    ("Panadería", "Tortilla"): "Panadería > Tortilla",
    ("Panadería", "Otros"): "Comida Preparada > Platos Preparados",
    # Pasta/Sopas
    ("Pasta/Sopas", "Arroz"): "Despensa > Arroz y Granos",
    ("Pasta/Sopas", "Fideos Instantáneos"): "Despensa > Fideos Instantáneos",
    ("Pasta/Sopas", "Granos"): "Despensa > Arroz y Granos",
    ("Pasta/Sopas", "Pasta"): "Despensa > Pasta",
    ("Pasta/Sopas", "Pasta Preparada"): "Comida Preparada > Platos Preparados",
    ("Pasta/Sopas", "Pasta Rellena"): "Despensa > Pasta Rellena",
    ("Pasta/Sopas", "Sopas"): "Despensa > Sopas",
    ("Pasta/Sopas", "Otros"): "Despensa > Otros",
    # Salud
    ("Salud", "Medicamentos"): "Cuidado Personal y Salud > Medicamentos",
    ("Salud", "Suplementos"): "Cuidado Personal y Salud > Otros",
    ("Salud", "Otros"): "Cuidado Personal y Salud > Otros",
    # Snacks
    ("Snacks", "Botanas"): ["Snacks > Botanas y Palomitas", "Comida Preparada > Platos Preparados"],
    ("Snacks", "Dips"): "Snacks > Dips",
    ("Snacks", "Frutos Secos"): "Despensa > Frutos Secos y Fruta Seca",
    ("Snacks", "Palomitas"): "Snacks > Botanas y Palomitas",
    ("Snacks", "Papas Fritas"): "Snacks > Papas Fritas",
    ("Snacks", "Totopos"): "Snacks > Totopos",
    ("Snacks", "Otros"): "Snacks > Otros",
}

# Reviewed corrections to split_llm results, stored as manual labels by `cli init`
# (or `cli overrides` on an initialised db). Sync never overwrites manual labels.
V2_OVERRIDES: Dict[str, str] = {
    "KIKKOMAN SOJASAUS": "Despensa > Salsas del Mundo",
    "KIK SOY SAUC": "Despensa > Salsas del Mundo",
    "WORCESTERSHIRE": "Despensa > Salsas del Mundo",
    "BOTERHAMZAKJES": "Hogar > Desechables de Cocina",
    "BOTERHAMZAKJES XI": "Hogar > Desechables de Cocina",
    "ROASTED KIP": "Comida Preparada > Platos Preparados",
    "LOEMPIA": "Comida Preparada > Platos Preparados",
    # review of flagged split_llm labels (2026-10-25): corrections
    "AH OVENGROEN": "Verduras > Mezclas de Verduras",
    "AH KOOL PEEN": "Verduras > Lechuga y Ensaladas",
    "JUMBO WITTE KAAS PL": "Lácteos y Huevos > Queso Italiano y Feta",
    "JO ROND SPELT HALF": "Panadería > Pan de Molde y Barra",
    "SALSA MED": "Snacks > Dips",
    "ECOVER": "Limpieza y Lavandería > Lavandería",
    # review of flagged split_llm labels (2026-10-25): approved as picked
    "JB SOEPGROENTE 400GR": "Verduras > Mezclas de Verduras",
    "JUMBO FIJNE SOEPGR": "Verduras > Mezclas de Verduras",
    "SOEPGROENTE": "Verduras > Mezclas de Verduras",
    "JUMBO RUNDERPOULET": "Carnes y Pescado > Res",
    "NECTARINES": "Frutas > Otros",
    "JUMBO PANEER NATUREL": "Lácteos y Huevos > Queso Fresco y Crema",
    "AH BIO KAAS": "Lácteos y Huevos > Queso Madurado",
    "BEEMSTER PUMPKIN SPI": "Lácteos y Huevos > Queso Madurado",
    "POLDERKAASJE": "Lácteos y Huevos > Queso Madurado",
    "KAASPLAKJES": "Lácteos y Huevos > Queso Madurado",
    "BROOD VAN GI": "Panadería > Pan de Molde y Barra",
    "HOME MADE SALSA": "Despensa > Salsas del Mundo",
    "GI OVENSAUS": "Despensa > Salsas para Pasta",
    "G ITAL PS TARTUFO": "Despensa > Salsas para Pasta",
    "TROP GOURMET": "Snacks > Botanas y Palomitas",
    "SORBO SPONS": "Limpieza y Lavandería > Limpiadores",
    "HG ONTSTOPP": "Limpieza y Lavandería > Limpiadores",
    "DIEPVRIESTAS": "Hogar > Bolsas Reutilizables",
    # review after first sync on the real db (2026-10-25): corrections
    "HEINZ TOM.KETCHUP": "Despensa > Aderezos",
    "AH SALADEMIX": "Verduras > Lechuga y Ensaladas",
    "JMB SALADMIX": "Verduras > Lechuga y Ensaladas",
    "JMB SALADEMIX": "Verduras > Lechuga y Ensaladas",
    "JUMBO PARM REG FLAKE": "Lácteos y Huevos > Queso Italiano y Feta",
    "MUTTI PS PARMIGIANO": "Despensa > Salsas para Pasta",
    "PATURAIN": "Lácteos y Huevos > Queso Fresco y Crema",
    "JUMBO ITALIAANS STK": "Lácteos y Huevos > Queso Madurado",
    "BIO AVOCADO": "Frutas > Frutas Tropicales",
    "AVOCADO": "Frutas > Frutas Tropicales",
    # review after first sync on the real db (2026-10-25): approved as picked
    "WITTE BOL X6": "Panadería > Panecillos",
    "STOOFBLOKJES": "Carnes y Pescado > Res",
    "SOEPVLEES": "Carnes y Pescado > Res",
    "FP MANCHEGO": "Lácteos y Huevos > Queso Madurado",
    "PAN TOSTADO TOM BAS": "Panadería > Pan de Molde y Barra",
    "KAISER WIT": "Panadería > Panecillos",
    "RIETSUIKER": "Despensa > Harina y Repostería",
    "OETK VANILLE": "Despensa > Harina y Repostería",
    # review of all split_llm labels on the real db (2026-10-25)
    "AH RUNDERBUR": "Carnes y Pescado > Hamburguesas y Albóndigas",
    "RUND TARTAAR": "Carnes y Pescado > Carne Molida",
    "TARTAAR NAT.": "Carnes y Pescado > Carne Molida",
    "AH GRF ROSBI": "Carnes y Pescado > Embutidos y Fiambres",
    "JUMBO ROSBIEF A MINU": "Carnes y Pescado > Embutidos y Fiambres",
    "SANMAR MIX FAJITA": "Despensa > Caldos y Sazonadores",
    "JUMBO WIT KAAS 2X50G": "Lácteos y Huevos > Queso Italiano y Feta",
    "AH WIT KAAS": "Lácteos y Huevos > Queso Italiano y Feta",
    "JUMBO WITTE KAAS": "Lácteos y Huevos > Queso Italiano y Feta",
    "JUMBO WITTE KAAS PI": "Lácteos y Huevos > Queso Italiano y Feta",
    "JUMBO GRANA PADAN ST": "Lácteos y Huevos > Queso Italiano y Feta",
    "KAASBOLLETJE": "Panadería > Panecillos",
    "STOKBROOD": "Panadería > Baguette",
    "WALDK STOKBR": "Panadería > Baguette",
    "KAISERBR VOLKOREN": "Panadería > Panecillos",
    "WITTE BOL": "Panadería > Panecillos",
    "AH BOTERHAMZ": "Hogar > Desechables de Cocina",
    "AH BLEEK": "Limpieza y Lavandería > Limpiadores",
    "BFYF HONDPOEPZAK 4R": "Hogar > Mascotas",
}
