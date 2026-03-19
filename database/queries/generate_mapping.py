{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": 12,
   "id": "a429fbf4",
   "metadata": {
    "scrolled": true
   },
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "✔ Nouveau mapping généré après réduction des catégories.\n"
     ]
    }
   ],
   "source": [
    "import pandas as pd\n",
    "from rapidfuzz import fuzz, process\n",
    "import re\n",
    "\n",
    "# -----------------------------\n",
    "# 1. Fonction pour extraire le mot-clé\n",
    "# -----------------------------\n",
    "def extract_head_category(cat):\n",
    "    if pd.isna(cat):\n",
    "        return None\n",
    "    # retirer les chiffres\n",
    "    cat = re.sub(r\"\\d+\", \"\", cat)\n",
    "    # convertir en minuscule\n",
    "    cat = cat.lower().strip()\n",
    "    # mots inutiles\n",
    "    STOP_WORDS = [\"from\", \"made\", \"with\", \"and\", \"their\", \"products\",\n",
    "                  \"conserve\", \"en\", \"de\", \"la\", \"le\", \"du\", \"year\", \"aged\"]\n",
    "    words = [w for w in cat.split() if w not in STOP_WORDS]\n",
    "\n",
    "    if not words:\n",
    "        return cat\n",
    "\n",
    "    # mot principal = le mot le plus long\n",
    "    return max(words, key=len)\n",
    "\n",
    "\n",
    "# -----------------------------\n",
    "# 2. Charger les catégories extraites\n",
    "# -----------------------------\n",
    "df = pd.read_csv(\"categories_extraites.csv\")\n",
    "raw_cats = df[\"clean_category\"].tolist()\n",
    "\n",
    "# -----------------------------\n",
    "# 3. Réduire chaque catégorie à un mot-clé\n",
    "# -----------------------------\n",
    "reduced_cats = [extract_head_category(c) for c in raw_cats]\n",
    "\n",
    "# -----------------------------\n",
    "# 4. Clustering avec RapidFuzz\n",
    "# -----------------------------\n",
    "clusters = {}\n",
    "SIMILARITY_THRESHOLD = 60\n",
    "\n",
    "for cat in reduced_cats:\n",
    "    matched = process.extractOne(cat, clusters.keys(), scorer=fuzz.ratio)\n",
    "    if matched and matched[1] >= SIMILARITY_THRESHOLD:\n",
    "        clusters[matched[0]].append(cat)\n",
    "    else:\n",
    "        clusters[cat] = [cat]\n",
    "\n",
    "# -----------------------------\n",
    "# 5. Construire le mapping final\n",
    "# -----------------------------\n",
    "mapping = []\n",
    "for main_cat, group in clusters.items():\n",
    "    for g in group:\n",
    "        mapping.append([g, main_cat])\n",
    "\n",
    "pd.DataFrame(mapping, columns=[\"raw_category\", \"final_category\"]) \\\n",
    "  .to_csv(\"categories_mapping.csv\", index=False)\n",
    "\n",
    "print(\"✔ Nouveau mapping généré après réduction des catégories.\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 2,
   "id": "03ba9da5",
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "Collecting rapidfuzz\n",
      "  Downloading rapidfuzz-3.13.0-cp39-cp39-win_amd64.whl.metadata (12 kB)\n",
      "Downloading rapidfuzz-3.13.0-cp39-cp39-win_amd64.whl (1.6 MB)\n",
      "   ---------------------------------------- 1.6/1.6 MB 2.2 MB/s  0:00:01\n",
      "Installing collected packages: rapidfuzz\n",
      "Successfully installed rapidfuzz-3.13.0\n",
      "Note: you may need to restart the kernel to use updated packages.\n"
     ]
    },
    {
     "name": "stderr",
     "output_type": "stream",
     "text": [
      "\n",
      "[notice] A new release of pip is available: 25.3 -> 26.0.1\n",
      "[notice] To update, run: python.exe -m pip install --upgrade pip\n"
     ]
    }
   ],
   "source": [
    "pip install rapidfuzz"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 13,
   "id": "b5036862",
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "Aperçu du mapping :\n",
      "  raw_category final_category\n",
      "0          NaN            NaN\n",
      "1          NaN            NaN\n",
      "2          NaN            NaN\n",
      "3          NaN            NaN\n",
      "4          NaN            NaN \n",
      "\n",
      "Nombre de catégories brutes AVANT clustering : 2554\n",
      "Nombre de catégories après clustering : 682\n",
      "\n",
      "→ Le clustering a réduit le nombre de catégories de 2554 à 682.\n",
      "\n",
      "Top 20 des clusters les plus grands (les plus de sous-catégories) :\n",
      "\n",
      "final_category\n",
      "alimentaires    28\n",
      "fruits          27\n",
      "aubergines      25\n",
      "calories        24\n",
      "creamer         24\n",
      "prepared        22\n",
      "protéines       22\n",
      "chocolate       20\n",
      "abricots        20\n",
      "aceites         19\n",
      "aromatised      18\n",
      "noires          18\n",
      "livers          17\n",
      "aiguillettes    17\n",
      "salad           17\n",
      "legumes         16\n",
      "acras           16\n",
      "ananas          14\n",
      "vegetable       14\n",
      "butters         14\n",
      "Name: raw_category, dtype: int64\n",
      "\n",
      "Fichier 'cluster_summary.csv' généré (résumé des clusters).\n"
     ]
    }
   ],
   "source": [
    "import pandas as pd\n",
    "\n",
    "# Charger le mapping obtenu après clustering\n",
    "df = pd.read_csv(\"categories_mapping.csv\")\n",
    "\n",
    "# Vérifier les 5 premières lignes\n",
    "print(\"Aperçu du mapping :\")\n",
    "print(df.head(), \"\\n\")\n",
    "\n",
    "# Nombre total de catégories initiales\n",
    "nb_raw = df[\"raw_category\"].nunique()\n",
    "print(f\"Nombre de catégories brutes AVANT clustering : {nb_raw}\")\n",
    "\n",
    "# Nombre de catégories finales (clusters)\n",
    "nb_final = df[\"final_category\"].nunique()\n",
    "print(f\"Nombre de catégories après clustering : {nb_final}\")\n",
    "\n",
    "print(\"\\n→ Le clustering a réduit le nombre de catégories de \"\n",
    "      f\"{nb_raw} à {nb_final}.\\n\")\n",
    "\n",
    "# Compter combien de catégories ont été regroupées dans chaque cluster\n",
    "cluster_counts = df.groupby(\"final_category\")[\"raw_category\"].nunique().sort_values(ascending=False)\n",
    "\n",
    "print(\"Top 20 des clusters les plus grands (les plus de sous-catégories) :\\n\")\n",
    "print(cluster_counts.head(20))\n",
    "\n",
    "# Sauvegarder un fichier d'analyse détaillée\n",
    "analysis_df = df.groupby(\"final_category\")[\"raw_category\"].nunique().reset_index()\n",
    "analysis_df.columns = [\"final_category\", \"nb_raw_categories\"]\n",
    "analysis_df.to_csv(\"cluster_summary.csv\", index=False)\n",
    "\n",
    "print(\"\\nFichier 'cluster_summary.csv' généré (résumé des clusters).\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "5ee23547",
   "metadata": {},
   "outputs": [],
   "source": []
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3 (ipykernel)",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.9.7"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
