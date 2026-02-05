import pandas as pd
import re

# Charger le fichier réduit
df = pd.read_csv("../reduit1.csv")

# Fonction pour vérifier si un texte est valide
def valeur_valide(val):
    if pd.isna(val):
        return False
    val = str(val).strip()
    return val != ""

##########################################################################
# Masque : product_name manquant ou vide
mask_product_missing = (
    df["product_name"].isna() |
    (df["product_name"].astype(str).str.strip() == "")
)

# Nombre de champs vides avant transformation
nb_vides = mask_product_missing.sum()
print(f"Nombre de champs vides de produit name avant transformation est {nb_vides}")

# Masque : generic_name valide
mask_generic_valid = df["generic_name"].apply(valeur_valide)

# Remplissage des product_name manquants avec generic_name
df.loc[
    mask_product_missing & mask_generic_valid,
    "product_name"
] = df.loc[
    mask_product_missing & mask_generic_valid,
    "generic_name"
]

# Vérification après remplissage
nb_vides_apres = df["product_name"].isna().sum()
print(f"Valeurs manquantes product_name après remplissage : {nb_vides_apres}")
print("\n \n")

#################################################################################################################
mask_brands_missing = (
    df["brands"].isna() |
    (df["brands"].astype(str).str.strip() == "")
)

# Nombre de champs vides avant transformation
nb_vides_brands = mask_brands_missing.sum()
print(f"Nombre de champs vides avant transformation de brands est {nb_vides_brands}")

# Masque : generic_name valide
mask_generic_valid_brands = df["brands_en"].apply(valeur_valide)

# Remplissage des product_name manquants avec generic_name
df.loc[
    mask_brands_missing & mask_generic_valid_brands,
    "brands"
] = df.loc[
    mask_brands_missing & mask_generic_valid_brands,
    "brands_en"
]

# Vérification après remplissage
nb_vides_apres = df["brands"].isna().sum()
print(f"Valeurs manquantes de brands après remplissage : {nb_vides_apres}")
print("\n \n")

##############################################################################################
nb_manquant_avant = (~df["categories"].apply(valeur_valide)).sum()
print(f"Nombre de catégories manquantes avant remplacement : {nb_manquant_avant}")

# Fonction pour remplir les catégories
def remplir_categories(row):
    if valeur_valide(row["categories_en"]):
        return row["categories_en"]
    elif valeur_valide(row["pnns_groups_1"]):
        return row["pnns_groups_1"]
    else:
        return row["categories"]

# Appliquer le remplissage
df["categories"] = df.apply(remplir_categories, axis=1)

# Compter le nombre de catégories manquantes après
nb_manquant_apres = (~df["categories"].apply(valeur_valide)).sum()
print(f"Nombre de catégories manquantes après remplacement : {nb_manquant_apres}")
print("\n \n")

#################################################################################################################
mask_labels_missing = (
    df["labels"].isna() |
    (df["labels"].astype(str).str.strip() == "")
)

# Nombre de champs vides avant transformation
nb_vides = mask_labels_missing.sum()
print(f"Nombre de champs vides avant transformation de labels est {nb_vides}")

# Masque : generic_name valide
mask_generic_valid_labels = df["labels_en"].apply(valeur_valide)

# Remplissage des product_name manquants avec generic_name
df.loc[
    mask_labels_missing & mask_generic_valid_labels,
    "labels"
] = df.loc[
    mask_labels_missing & mask_generic_valid_labels,
    "labels_en"
]

# Vérification après remplissage
nb_vides_apres = df["labels"].isna().sum()
print(f"Valeurs manquantes de labels après remplissage : {nb_vides_apres}")
print("\n \n")

#################################################################################################################
mask_allergens_missing = (
    df["allergens"].isna() |
    (df["allergens"].astype(str).str.strip() == "")
)

# Nombre de champs vides avant transformation
nb_vides = mask_allergens_missing.sum()
print(f"Nombre de champs vides avant transformation de allergens est {nb_vides}")

# Masque : generic_name valide
mask_generic_valid_allergens = df["allergens_en"].apply(valeur_valide)

# Remplissage des product_name manquants avec generic_name
df.loc[
    mask_allergens_missing & mask_generic_valid_allergens,
    "allergens"
] = df.loc[
    mask_allergens_missing & mask_generic_valid_allergens,
    "allergens_en"
]

# Vérification après remplissage
nb_vides_apres = df["allergens"].isna().sum()
print(f"Valeurs manquantes de allergens après remplissage : {nb_vides_apres}")
print("\n \n")

###############################################""
mask_traces_missing = (
    df["traces"].isna() |
    (df["traces"].astype(str).str.strip() == "")
)

# Nombre de champs vides avant transformation
nb_vides = mask_traces_missing.sum()
print(f"Nombre de champs vides avant transformation de traces est {nb_vides}")

# Masque : generic_name valide
mask_generic_valid_traces = df["traces_en"].apply(valeur_valide)

# Remplissage des product_name manquants avec generic_name
df.loc[
    mask_traces_missing & mask_generic_valid_traces,
    "traces"
] = df.loc[
    mask_traces_missing & mask_generic_valid_traces,
    "traces_en"
]

# Vérification après remplissage
nb_vides_apres = df["traces"].isna().sum()
print(f"Valeurs manquantes de traces après remplissage : {nb_vides_apres}")
print("\n \n")

####################