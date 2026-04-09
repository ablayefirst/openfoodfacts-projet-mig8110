import pandas as pd
import re

FILE_PATH = "../reduit.csv"

df = pd.read_csv(FILE_PATH, sep=",", encoding="utf-8")

def normaliser_quantity(q):
    if pd.isna(q):
        return None

    morceaux = str(q).lower().split(",")

    for m in morceaux:
        m = m.strip().replace(" ", "")

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

        if unit == "kg":
            valeur, unit = valeur * 1000, "g"
        elif unit == "oz":
            valeur, unit = valeur * 28.3495, "g"
        elif unit == "ml":
            valeur, unit = valeur / 1000, "L"
        elif unit == "cl":
            valeur, unit = valeur / 100, "L"
        elif unit == "dl":
            valeur, unit = valeur / 10, "L"
        elif unit == "l":
            unit = "L"

        return f"{round(valeur, 3)} {unit}"

    return None

# Normalisation
df["quantity"] = df["quantity"].apply(normaliser_quantity)

# Vérification visuelle
print(df["quantity"].sample(20))

# ÉCRASE le fichier original
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Champ quantity normalisé et fichier mis à jour")
