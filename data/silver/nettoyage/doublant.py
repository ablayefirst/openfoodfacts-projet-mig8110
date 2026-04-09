import pandas as pd

# Charger les données
df = pd.read_csv("../reduit.csv", engine="python")

# Nombre de lignes avant suppression
nb_avant = df.shape[0]

# Suppression des doublons basés sur le code-barres
df = df.drop_duplicates(subset=["code"])

# Nombre de lignes après suppression
nb_apres = df.shape[0]

print(f"Lignes avant suppression des doublons : {nb_avant}")
print(f"Lignes après suppression des doublons : {nb_apres}")
print(f"Doublons supprimés : {nb_avant - nb_apres}")
