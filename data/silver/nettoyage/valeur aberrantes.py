import pandas as pd
import re

FILE_PATH = "../reduit1.csv"
df = pd.read_csv(FILE_PATH, encoding="utf-8")

cols = [
    "quantity",
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

def extract_value_unit(x):
    """
    Retourne (nombre, unité, texte original sans unité)
    """
    if pd.isna(x):
        return None, "", None

    x_str = str(x).strip()

    # unité = tout ce qui est à la fin (lettres ou parenthèses)
    unit_match = re.search(r"[a-zA-Z\(\)]+$", x_str)
    unit = unit_match.group(0) if unit_match else ""

    # nombre = tout ce qui est avant l'unité
    number_str = x_str.replace(unit, "").strip()
    number_str = number_str.replace(",", ".")
    number_str = re.sub(r"[^\d\.]", "", number_str)

    if number_str == "":
        return None, unit, None

    try:
        return float(number_str), unit, number_str
    except:
        return None, unit, None

def correct_outliers(series):
    # Extraire nombres
    numeric = series.apply(lambda x: extract_value_unit(x)[0])
    s = numeric.dropna()

    if len(s) == 0:
        return numeric, None, None, None

    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1

    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    median = s.median()

    corrected = []
    for x in numeric:
        if x is None:
            corrected.append(None)
        elif x < low or x > high:
            corrected.append(median)
        else:
            corrected.append(x)

    return corrected, low, high, median

# ======== Correction ========
for col in cols:
    corrected_values, low, high, median = correct_outliers(df[col])

    new_col = []
    for orig, corr in zip(df[col], corrected_values):
        val, unit, val_str = extract_value_unit(orig)

        # si valeur manquante => garde original
        if val is None:
            new_col.append(orig)
            continue

        # si valeur non aberrante => garde original
        if corr == val:
            new_col.append(orig)
            continue

        # si aberrante => mediane(old) unit
        new_col.append(f"{corr}({val_str}) {unit}".strip())

    df[col] = new_col

# ======== Sauvegarde ========
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Correction terminée (format mediane(old) unité)")
