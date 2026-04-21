import pandas as pd
import math

FILE_PATH = "../reduit1.csv"

KCAL_COL = "energy-kcal_100g"
KJ_COL = "energy-kj_100g"
ENERGY_COL = "energy_100g"

TOLERANCE = 2  # kJ

df = pd.read_csv(FILE_PATH, encoding="utf-8")

def is_nan(x):
    return pd.isna(x) or x == ""

for i, row in df.iterrows():
    kcal = row.get(KCAL_COL)
    kj = row.get(KJ_COL)
    energy = row.get(ENERGY_COL)

    # Nettoyage types
    kcal = float(kcal) if not is_nan(kcal) else None
    kj = float(kj) if not is_nan(kj) else None
    energy = float(energy) if not is_nan(energy) else None

    # =========================
    # CAS 1 : kcal présent
    # =========================
    if kcal is not None:
        kj_calc = round(kcal * 4.184, 1)

        # kj absent ou faux
        if kj is None or abs(kj - kj_calc) > TOLERANCE:
            df.at[i, KJ_COL] = kj_calc
            df.at[i, ENERGY_COL] = kj_calc
        else:
            df.at[i, ENERGY_COL] = kj

    # =========================
    # CAS 2 : kcal absent, kj présent
    # =========================
    elif kj is not None:
        kcal_calc = round(kj / 4.184, 1)
        df.at[i, KCAL_COL] = kcal_calc
        df.at[i, ENERGY_COL] = kj

    # =========================
    # CAS 3 : seul energy présent
    # =========================
    elif energy is not None:
        df.at[i, KJ_COL] = energy
        df.at[i, KCAL_COL] = round(energy / 4.184, 1)

# =========================
# SAUVEGARDE (écrase fichier)
# =========================
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Énergie vérifiée, corrigée et complétée")
