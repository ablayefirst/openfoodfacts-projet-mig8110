import pandas as pd

# Charger le fichier
df = pd.read_csv("../reduit.csv", sep=",", encoding="utf-8")

# Fonction pour vérifier si une valeur est vide
def valeur_valide(val):
    if pd.isna(val):
        return False
    val = str(val).strip()
    return val != ""

# Compter le nombre de catégories manquantes avant
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

# Vérification rapide
print(df[["categories", "categories_en", "pnns_groups_1"]].sample(10))
