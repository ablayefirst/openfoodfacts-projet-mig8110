import pandas as pd
import re

# Charger le fichier réduit
df = pd.read_csv("../reduit.csv")

# Fonction pour vérifier si un texte est valide
def texte_valide(val):
    if pd.isna(val):
        return False
    val = str(val).strip()
    # Vérifie s'il contient au moins une lettre ou un chiffre
    return bool(re.search(r"[A-Za-z0-9]", val))

##########################################################################
# Masque : product_name manquant ou vide
mask_product_missing = (
    df["brands"].isna() |
    (df["brands"].astype(str).str.strip() == "")
)

# Nombre de champs vides avant transformation
nb_vides = mask_product_missing.sum()
print(f"Nombre de champs vides avant transformation est {nb_vides}")

# Masque : generic_name valide
mask_generic_valid = df["brands_en"].apply(texte_valide)

# Remplissage des product_name manquants avec generic_name
df.loc[
    mask_product_missing & mask_generic_valid,
    "brands"
] = df.loc[
    mask_product_missing & mask_generic_valid,
    "brands_en"
]

# Vérification après remplissage
nb_vides_apres = df["product_name"].isna().sum()
print(f"Valeurs manquantes de brands après remplissage : {nb_vides_apres}")


