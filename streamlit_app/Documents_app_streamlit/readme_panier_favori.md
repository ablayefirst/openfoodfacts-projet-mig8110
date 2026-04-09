# Readme – Fonctionnalité « Panier favori » (liste de favoris)

## 1. Objectif de la fonctionnalité

La fonctionnalité **« Panier favori »** permet à l’utilisateur de constituer une **liste de produits favoris** (panier santé) directement depuis le Dashboard.

L’objectif est de :
- mémoriser les produits jugés intéressants pour un suivi ultérieur,
- retrouver ces produits rapidement dans une page dédiée,
- identifier, au sein de ce panier, le ou les produits **les plus adaptés** au profil santé de l’utilisateur (si le profil est activé).

Cette fonctionnalité complète le Dashboard, le comparateur et le profil santé en offrant une **vision centrée sur les produits favoris de l’utilisateur**.

---

## 2. Localisation dans l’application

- Ajout / retrait de favoris : depuis le **Dashboard principal** (`streamlit_app/main.py`).
- Consultation du panier : page **« Favoris »** (`streamlit_app/pages/04_panier_favori.py`).

Sur le Dashboard :
- chaque carte produit contient un bouton **« Ajouter aux favoris »** ou **« Retirer des favoris »**,
- les codes produits ajoutés sont stockés dans `st.session_state.favorites`.

Sur la page Favoris :
- seuls les produits dont le code figure dans `st.session_state.favorites` sont affichés,
- les produits sont présentés sous forme de **cartes** riches (photo, NutriScore, NOVA, sucre, sel, etc.).

---

## 3. Ajout et suppression de produits favoris

### 3.1. Depuis le Dashboard (main.py)

Pour chaque produit affiché dans le Dashboard :

- l’interface affiche un bouton :
  - **« Ajouter aux favoris »** si le produit **n’est pas encore** dans la liste de favoris,
  - **« Retirer des favoris »** si le produit **est déjà** dans la liste.

- Lors d’un clic sur ce bouton :
  - si le produit n’était pas favori, son `code` est **ajouté** à `st.session_state.favorites`,
  - s’il était déjà favori, son `code` est **supprimé** de cette liste.

Cette liste persiste tant que la session Streamlit reste active.

### 3.2. Logique de stockage

- Le panier de favoris est représenté par :
  - `st.session_state.favorites` : **liste** de codes produits (chaînes de caractères).
- Aucun doublon n’est nécessaire : lorsqu’un produit est déjà dans la liste, cliquer à nouveau sur « Ajouter aux favoris » ne le duplique pas, le bouton bascule simplement en mode retrait.

---

## 4. Contenu et affichage de la page « Favoris »

La page `streamlit_app/pages/04_panier_favori.py` se charge d’afficher uniquement les produits favoris.

### 4.1. Chargement des données

1. Lecture de la liste des codes favoris depuis `st.session_state.favorites`.
2. Si la liste est vide :
   - la page affiche un message indiquant que **aucun produit n’a encore été ajouté** au panier favori.
3. Sinon :
   - une requête SQL sélectionne, dans la base PostgreSQL, tous les produits dont le `code_produit` figure dans cette liste,
   - les données nutritionnelles principales (sucre, sel, NutriScore, NOVA, etc.) sont récupérées.

### 4.2. Cartes produits dans le panier

Pour chaque produit favori, la page affiche une **carte** similaire à celles du Dashboard :

- **Image** du produit :
  - si `image_url` est renseignée, elle est utilisée directement,
  - sinon, une image par défaut est fournie par `get_no_image_data_uri` (fichier `no_image.png`).

- **Informations principales** :
  - nom du produit,
  - catégorie principale et catégories détaillées,
  - NutriScore (A–E),
  - NOVA (degré de transformation),
  - sucre (g/100g),
  - sel (g/100g).

- **Actions** :
  - bouton **« Retirer des favoris »** qui supprime le produit de `st.session_state.favorites` et rafraîchit la page,
  - éventuellement un bouton pour revenir au Dashboard.

---

## 5. Intégration avec le profil santé

Si l’utilisateur a défini un **profil santé** (page « Mon profil santé ») et que le tri personnalisé est activé :

- la fonction `compute_personalized_scores` (définie dans `health_logic.py`) est utilisée pour calculer un **score personnalisé** pour chaque produit du panier,
- ce score tient compte :
  - du NutriScore,
  - du sucre et du sel,
  - des pénalités choisies (sucre/sel) et de l’objectif du profil santé.

Dans ce cas, la page « Favoris » peut :
- trier les produits favoris par score personnalisé (les plus adaptés en premier),
- mettre en avant le **meilleur produit** (par exemple, celui avec le score le plus élevé dans le panier).

Si aucun profil n’est actif :
- la page affiche simplement les produits favoris avec leurs informations nutritionnelles,
- l’utilisateur peut tout de même repérer visuellement les produits plus favorables (NutriScore A/B, moins de sucre/sel, etc.).

---

## 6. Cas particuliers et comportements attendus

- **Panier vide** :
  - un message explicite rappelle à l’utilisateur d’ajouter des produits depuis le Dashboard.

- **Produit supprimé de la base** :
  - si un code favori n’existe plus en base, il n’apparaît pas dans la liste des cartes,
  - la logique peut, le cas échéant, nettoyer la liste `favorites` pour retirer ce code.

- **Profil santé très restrictif** :
  - si un profil avec des pénalités très élevées (sucre/sel) est actif, il est possible que très peu de produits du panier restent « compatibles » d’un point de vue score personnalisé,
  - dans ce cas, la page doit l’indiquer clairement (par exemple, en affichant qu’aucun produit favori ne correspond vraiment aux critères).

---

## 7. Parcours utilisateur typique

1. Sur le Dashboard, l’utilisateur parcourt les produits, applique ses filtres et (éventuellement) active son profil santé.
2. Pour chaque produit jugé intéressant, il clique sur **« Ajouter aux favoris »**.
3. Il se rend ensuite sur la page **« Favoris »** :
   - il retrouve l’ensemble de ses produits favoris rassemblés,
   - il peut visualiser pour chacun les informations nutritionnelles clés.
4. Si un profil santé est actif, il peut voir **quel produit de son panier est le plus adapté** à ses critères.
5. Il peut retirer certains produits de la liste pour **affiner progressivement** son panier.

---

## 8. Intérêt de la fonctionnalité

Le « Panier favori » apporte plusieurs bénéfices :

- permet de **mettre de côté** des produits intéressants repérés lors de la navigation,
- sert de base à une **liste de courses santé** ou à une shortlist de produits à acheter,
- s’intègre naturellement avec le profil santé pour proposer un **panier aligné avec les objectifs de l’utilisateur**.

Cette fonctionnalité renforce l’idée d’un **assistant nutritionnel personnalisé**, qui ne se contente pas d’afficher des informations, mais aide aussi l’utilisateur à structurer ses choix sur le long terme.
