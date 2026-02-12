import pandas as pd
import re

FILE_PATH = "../../dataset/brut/nettoyage/netoyer1.csv"

# Charger le CSV
df = pd.read_csv(FILE_PATH, sep=",", encoding="utf-8")

# Fonction pour normaliser la quantité et retourner juste le chiffre
def normaliser_quantity(q):
    if pd.isna(q):
        return None

    morceaux = str(q).lower().split(",")

    for m in morceaux:
        m = m.strip().replace(" ", "")

        # Cas multiplicatif (ex: 2x500g)
        mult = re.match(r"(\d+(?:\.\d+)?)[x×](\d+(?:\.\d+)?)(kg|g|oz|ml|cl|dl|l)", m)
        if mult:
            a, b, unit = mult.groups()
            valeur = float(a) * float(b)
        else:
            match = re.match(r"(\d+(?:\.\d+)?)(kg|g|oz|ml|cl|dl|l)", m)
            if not match:
                continue

            valeur, unit = match.groups()
            valeur = float(valeur)

        # Conversion en grammes ou litres
        if unit == "kg":
            valeur = valeur * 1000
        elif unit == "oz":
            valeur = valeur * 28.3495
        elif unit == "ml":
            valeur = valeur / 1000
        elif unit == "cl":
            valeur = valeur / 100
        elif unit == "dl":
            valeur = valeur / 10
        # l reste en litres, pas besoin de conversion

        return round(valeur, 3)  # juste le chiffre, unité supprimée

    return None

# Normalisation
df["quantity"] = df["quantity"].apply(normaliser_quantity)

# Renommer la colonne
df = df.rename(columns={"quantity": "quantity(g)"})

# Vérification visuelle
print(df[["quantity(g)"]].sample(10))

# Écrase le fichier original
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Champ quantity normalisé et colonne renommée en 'quantity(g)'. Fichier mis à jour !")
