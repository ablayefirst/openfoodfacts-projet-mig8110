import pandas as pd

df = pd.read_csv("../../gold/nettoye.csv")

for col in df.columns:
    if df[col].dtype == 'object':
        df[col] = (
            df[col]
            .fillna('')
            .str.lower()
            .str.replace('fr:', '', regex=False)
            .str.replace(' fr:', '', regex=False)
            .str.replace(',fr:', ',', regex=False)
            .str.replace('en:', '', regex=False)
            .str.strip()
        )
        df[col] = df[col].replace('', 'unknow')


# Supprimer colonnes Unnamed
df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

print("Colonnes Unnamed supprimées et fichier nettoyé ✅")

df.to_csv("../../gold/nettoye.csv", index=False)

print("Nettoyage terminé")
