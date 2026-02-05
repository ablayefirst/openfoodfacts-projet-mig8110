import pandas as pd

FILE_PATH = "../reduit1.csv"

GRADE_COL = "nutriscore_grade"

df = pd.read_csv(FILE_PATH, encoding="utf-8")

def is_nan(x):
    return pd.isna(x) or x == ""

def clean_grade(g):
    if is_nan(g):
        return None

    g = str(g).strip().upper()  # majuscule + nettoyage

    # cas normal : 1 caractère
    if len(g) == 1 and g in ["A", "B", "C", "D", "E"]:
        return g

    # cas anormal : plus d'un caractère
    # on cherche A ou B ou C ou D ou E dans la chaîne
    for c in ["A", "B", "C", "D", "E"]:
        if c in g:
            return c

    # si rien trouvé
    return None

# ================
# NETTOYAGE
# ================
df[GRADE_COL] = df[GRADE_COL].apply(clean_grade)

# ================
# SAUVEGARDE
# ================
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Nutriscore normalisé (MAJ + 1 caractère)")
