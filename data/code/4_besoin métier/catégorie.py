import pandas as pd

df = pd.read_csv("../../dataset/brut/nettoyage/netoyer1.csv")

# for col in df.columns:
#     if df[col].dtype == 'object':
#         df[col] = df[col].fillna('').str.replace(r'en:', '', regex=True).str.strip()

df["categories"] = (
    df["categories"]
    .str.strip()                       # enlever les espaces début/fin
    .str.split(r",\s*")                # séparer par virgule et espaces
    .apply(lambda x: list(dict.fromkeys(x)))  # supprimer doublons en conservant l'ordre
)
print(df["categories"])


df.info()
# 🔹 Afficher le résultat
df.to_csv("../../dataset/brut/nettoyage/netoyer1.csv", index=False)