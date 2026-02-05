import pandas as pd

FILE_PATH = "../reduit1.csv"

SALT_COL = "salt_100g"
SODIUM_COL = "sodium_100g"

TOLERANCE_SALT = 0.01     # g
TOLERANCE_SODIUM = 5      # mg

df = pd.read_csv(FILE_PATH, encoding="utf-8")

def is_nan(x):
    return pd.isna(x) or x == ""

for i, row in df.iterrows():
    salt = row.get(SALT_COL)
    sodium = row.get(SODIUM_COL)

    # Nettoyage types
    salt = float(salt) if not is_nan(salt) else None
    sodium = float(sodium) if not is_nan(sodium) else None

    # =========================
    # CAS 1 : salt présent
    # =========================
    if salt is not None:
        sodium_calc = round(salt * 400, 1)

        # sodium absent ou incorrect
        if sodium is None or abs(sodium - sodium_calc) > TOLERANCE_SODIUM:
            df.at[i, SODIUM_COL] = sodium_calc

    # =========================
    # CAS 2 : sodium présent, salt absent
    # =========================
    elif sodium is not None:
        salt_calc = round(sodium / 400, 3)
        df.at[i, SALT_COL] = salt_calc

# =========================
# SAUVEGARDE (écrase fichier)
# =========================
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Sel et sodium vérifiés, corrigés et complétés")
