import pandas as pd
import re
import numpy as np

FILE_PATH = "../../dataset/brut/nettoyage/netoyer1.csv"
df = pd.read_csv(FILE_PATH, encoding="utf-8")

cols = [
    "quantity(g)",
    "nutriscore_score",
    "energy_100g",
    "fat_100g",
    "saturated-fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g"
]

def extract_numeric(x):
    """Extrait le nombre d'une cellule, ignore l'unité"""
    if pd.isna(x):
        return np.nan
    x_str = str(x).strip()
    x_str = x_str.replace(",", ".")
    # supprimer tout sauf chiffres et point
    x_str = re.sub(r"[^\d\.]", "", x_str)
    try:
        return float(x_str)
    except:
        return np.nan

def replace_outliers_with_nan(series):
    """Remplace les valeurs aberrantes par NaN selon IQR"""
    numeric = series.apply(extract_numeric)
    s = numeric.dropna()
    if len(s) == 0:
        return series  # rien à corriger

    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr

    # remplacer aberrantes par NaN
    corrected = numeric.apply(lambda x: x if low <= x <= high else np.nan)
    return corrected

# ======== Correction ========
for col in cols:
    df[col] = replace_outliers_with_nan(df[col])

# ======== Sauvegarde ========
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Correction terminée : valeurs aberrantes remplacées par NaN")
