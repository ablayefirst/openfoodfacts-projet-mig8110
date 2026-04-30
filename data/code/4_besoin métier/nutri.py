import pandas as pd

FILE_PATH = "../../dataset/brut/nettoyage/netoyer1.csv"

# Lecture du CSV
df = pd.read_csv(FILE_PATH, encoding="utf-8")

# Dictionnaire grade → score
GRADE_TO_SCORE = {
    "A": -1,
    "B": 1,
    "C": 7,
    "D": 15,
    "E": 19
}

# Fonction score → grade
def score_to_grade(score):
    try:
        score = int(score)
    except:
        return None
    if score <= -1:
        return "A"
    elif score <= 2:
        return "B"
    elif score <= 10:
        return "C"
    elif score <= 18:
        return "D"
    else:
        return "E"

GRADE_COL = "nutriscore_grade"
SCORE_COL = "nutriscore_score"

# Remplir les grades manquants avec les scores
mask_grade_missing = df[GRADE_COL].isna() | (df[GRADE_COL].str.strip() == "")
df.loc[mask_grade_missing & df[SCORE_COL].notna(), GRADE_COL] = df.loc[mask_grade_missing & df[SCORE_COL].notna(), SCORE_COL].apply(score_to_grade)

# Remplir les scores manquants avec les grades
mask_score_missing = df[SCORE_COL].isna() | (df[SCORE_COL].astype(str).str.strip() == "")
df.loc[mask_score_missing & df[GRADE_COL].notna(), SCORE_COL] = df.loc[mask_score_missing & df[GRADE_COL].notna(), GRADE_COL].map(GRADE_TO_SCORE)

# Sauvegarder le CSV
df.to_csv(FILE_PATH, index=False, encoding="utf-8")

print("Fichier mis à jour avec pandas :", FILE_PATH)
