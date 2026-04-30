import pandas as pd

# Charger le fichier réduit
df = pd.read_csv("../../dataset/brut/nettoyage/netoyer1.csv")

# Fonction pour vérifier si un texte est valide (non vide, non NaN)
def valeur_valide(val):
    if pd.isna(val):
        return False
    val = str(val).strip()
    return val != ""

# Fonction générique pour remplir une colonne avec sa version anglaise si vide
def remplir_champ(df, col, col_en):
    nb_vides_avant = (~df[col].apply(valeur_valide)).sum()
    print(f"Valeurs manquantes de {col} avant remplissage : {nb_vides_avant}")

    mask_missing = ~df[col].apply(valeur_valide)
    mask_valid_en = df[col_en].apply(valeur_valide)

    df.loc[mask_missing & mask_valid_en, col] = df.loc[mask_missing & mask_valid_en, col_en]

    nb_vides_apres = (~df[col].apply(valeur_valide)).sum()
    print(f"Valeurs manquantes de {col} après remplissage : {nb_vides_apres}\n")

# Liste des colonnes à traiter avec leur version anglaise correspondante
colonnes_a_remplir = [
    ("product_name", "generic_name"),
    ("brands", "brands_en"),
    ("labels", "labels_en"),
    ("allergens", "allergens_en"),
    ("traces", "traces_en")
]

# Remplissage automatique
for col, col_en in colonnes_a_remplir:
    remplir_champ(df, col, col_en)

# Traitement spécifique pour les categories
nb_manquant_avant = (~df["categories"].apply(valeur_valide)).sum()
print(f"Nombre de catégories manquantes avant remplacement : {nb_manquant_avant}")

# Remplissage des categories avec priorité : categories_en > food_groups_en > categories
df["categories"] = df["categories"].where(df["categories"].apply(valeur_valide), df["categories_en"])
df["categories"] = df["categories"].where(df["categories"].apply(valeur_valide), df["food_groups_en"])

nb_manquant_apres = (~df["categories"].apply(valeur_valide)).sum()
print(f"Nombre de catégories manquantes après remplacement : {nb_manquant_apres}\n")

# Sauvegarde du DataFrame dans le même fichier CSV
df.to_csv("../../dataset/brut/nettoyage/netoyer1.csv", index=False)
print("Fichier sauvegardé avec succès !")
