import pandas as pd

df = pd.read_csv("../../dataset/brut/nettoyage/netoyer1.csv")

# Fonction pour nettoyer et supprimer les doublons dans les ingrédients
def nettoyer_ingredients(text):
    if pd.isna(text):  # gérer les NaN
        return None
    # séparer par virgule, enlever les espaces, supprimer doublons en conservant l'ordre
    parts = [p.strip() for p in text.split(",")]
    return list(dict.fromkeys(parts))

# Appliquer la fonction
df["ingredients_text"] = df["ingredients_text"].apply(nettoyer_ingredients)

# Vérification
print(df["ingredients_text"].sample(10))

# Sauvegarde
df.to_csv("../../dataset/brut/nettoyage/netoyer1.csv", index=False)
print("ingredients_text nettoyé et fichier mis à jour !")
