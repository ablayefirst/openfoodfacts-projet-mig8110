import pandas as pd

df = pd.read_csv("../../dataset/brut/nettoyage/netoyer1.csv")

for col in df.columns:
    if df[col].dtype == 'object':
        df[col] = (
            df[col]
            .fillna('')
            .str.replace(r'en:', '', regex=True)
            .str.strip()
        )
        df[col] = df[col].replace('', 'unknow')



# 🔥 Supprime toutes les colonnes dont le nom commence par "Unnamed"
df = df.loc[:, ~df.columns.str.contains("^Unnamed")]



print("Colonnes Unnamed supprimées et fichier nettoyé ✅")


df.to_csv("../../dataset/brut/nettoyage/netoyer1.csv", index=False)
print("Nettoyage terminé")
