import csv
import os

FILE_PATH = "../reduit1.csv"
TMP_FILE = "reduit_tmp.csv"

GRADE_COL = "off:nutriscore_grade"
SCORE_COL = "off:nutriscore_score"

# Scores fixes par grade
GRADE_TO_SCORE = {
    "A": -1,
    "B": 1,
    "C": 7,
    "D": 15,
    "E": 19
}

def score_to_grade(score):
    score = int(score)
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

# Lecture + écriture dans un fichier temporaire
with open(FILE_PATH, encoding="utf-8") as f, \
     open(TMP_FILE, "w", encoding="utf-8", newline="") as out:

    reader = csv.DictReader(f, delimiter=",")
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames, delimiter=",")

    writer.writeheader()

    for row in reader:
        grade = row.get(GRADE_COL, "").strip().upper()
        score = row.get(SCORE_COL, "").strip()

        # score présent, grade manquant
        if score != "" and grade == "":
            row[GRADE_COL] = score_to_grade(score)

        # grade présent, score manquant
        elif grade in GRADE_TO_SCORE and score == "":
            row[SCORE_COL] = str(GRADE_TO_SCORE[grade])

        writer.writerow(row)

# Remplacer l'ancien fichier par le nouveau
os.replace(TMP_FILE, FILE_PATH)

print("Fichier mis à jour :", FILE_PATH)
