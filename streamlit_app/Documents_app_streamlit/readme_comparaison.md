# Readme – Fonctionnalité « Comparateur de produits »

## 1. Objectif de la fonctionnalité

Le **comparateur de produits** permet à l’utilisateur de sélectionner 2 à 3 produits depuis le Dashboard et de les comparer **côte à côte** sur plusieurs critères nutritionnels et de santé.

Cette fonctionnalité aide l’utilisateur à :
- visualiser rapidement les différences entre plusieurs produits similaires,
- identifier le produit **le plus adapté** à son profil santé (si le profil est activé),
- prendre une décision éclairée (par exemple, choisir les céréales les moins sucrées parmi 3 références).

---

## 2. Localisation dans l’application

- Sélection des produits : depuis le **Dashboard** (`streamlit_app/main.py`).
- Page de comparaison : `streamlit_app/pages/03_comparateur_produits.py`.

Sur le Dashboard :
- chaque carte produit contient une **case à cocher** « Comparer »,
- un compteur indique le nombre de produits sélectionnés,
- un bouton « Comparer les produits sélectionnés » permet d’ouvrir la page de comparaison.

Sur la page Comparateur :
- les produits sélectionnés sont affichés **en colonnes** avec leurs informations principales.

---

## 3. Règles de sélection

- L’utilisateur peut sélectionner **au minimum 2 produits** et **au maximum 3 produits**.
- Si l’utilisateur tente de sélectionner un 4ᵉ produit :
  - un message d’information s’affiche :
    - « Vous ne pouvez comparer que 3 produits à la fois. Décochez un produit avant d'en ajouter un autre. »
  - le 4ᵉ produit **n’est pas ajouté** à la liste de comparaison.
- Le bouton « Comparer les produits sélectionnés » :
  - affiche un avertissement si **moins de 2 produits** sont sélectionnés,
  - redirige vers la page de comparaison si la sélection est valide.

Ces règles garantissent une comparaison lisible, sans surcharger l’écran.

---

## 4. Informations affichées dans le comparateur

Pour chaque produit sélectionné, la page `03_comparateur_produits.py` affiche notamment :

- **Informations générales** :
  - nom du produit,
  - catégories principales / détaillées,
  - éventuelles informations complémentaires (marque, pays, etc., selon les données disponibles).

- **Scores de santé** :
  - NutriScore (A à E),
  - NOVA (niveau de transformation des aliments).

- **Valeurs nutritionnelles clés** :
  - sucre (g/100g),
  - sel (g/100g),
  - graisses saturées (g/100g),
  - fibres (g/100g),
  - protéines (g/100g).

L’affichage côte à côte permet de repérer facilement quel produit est :
- le plus sucré,
- le plus salé,
- le plus transformé (NOVA),
- ou au contraire le plus équilibré.

---

## 5. Intégration avec le profil santé

Si l’utilisateur a défini un profil dans **« Mon profil santé »** et que le tri personnalisé est activé :

- la fonction `compute_personalized_scores` (définie dans `health_profile.py`) est réutilisée pour calculer un **score personnalisé** pour chaque produit comparé ;
- ce score tient compte du NutriScore, du sucre, du sel, et des objectifs/contraintes du profil (diabète, hypertension, etc.).

Dans ce cas, la page comparateur :
- affiche éventuellement ce score ou l’utilise en interne,
- met en avant le produit qui obtient **le meilleur score** pour cet utilisateur.

Si aucun profil n’est actif :
- la comparaison reste possible,
- le « meilleur choix » peut être évalué à partir de critères plus simples (par exemple, meilleur NutriScore).

---

## 6. Détermination du « meilleur produit »

En bas de la page comparateur, une section **« Meilleur choix parmi ces produits »** est affichée.

La logique est la suivante :

1. Si un **score personnalisé** est disponible (profil actif) :
   - on choisit le produit avec le **score le plus élevé** ;
2. Sinon :
   - on peut se baser sur le NutriScore, en convertissant A–E en score numérique (A = 5, …, E = 1),
   - le produit avec le meilleur score NutriScore est mis en avant.

La section affiche :

- le **nom du produit recommandé**,
- un rappel des raisons (ex. « meilleur NutriScore » ou « score personnalisé le plus élevé pour votre profil »),
- éventuellement une brève explication sur ce qui le différencie des autres (souvent moins sucré ou moins salé).

---

## 7. Parcours utilisateur typique

1. L’utilisateur filtre les produits sur le Dashboard (ex. céréales pour le petit-déjeuner).
2. Il coche la case **« Comparer »** sur 2 ou 3 produits jugés intéressants.
3. Il clique sur **« Comparer les produits sélectionnés »**.
4. Sur la page comparateur :
   - il examine les NutriScore, NOVA et valeurs nutritionnelles,
   - il se base sur le **meilleur choix** mis en avant pour faire son achat.
5. Il peut revenir au Dashboard pour modifier sa sélection ou consulter d’autres produits.

Si un profil santé est actif, ce parcours est encore plus pertinent car le comparateur met en avant le produit le plus compatible avec ce profil.

---

## 8. Intérêt de la fonctionnalité

Le comparateur de produits complète le Dashboard et le profil santé en offrant :

- une **aide à la décision** concrète au moment du choix entre plusieurs produits,
- une meilleure compréhension des différences nutritionnelles entre produits similaires,
- un support pédagogique pour expliquer l’impact du NutriScore, du sucre, du sel et des profils de santé.

C’est une fonctionnalité clé pour illustrer la valeur ajoutée de l’application.
