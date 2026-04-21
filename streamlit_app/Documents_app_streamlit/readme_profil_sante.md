# Readme – Fonctionnalité « Mon profil santé »

## 1. Objectif de la fonctionnalité

La fonctionnalité « Mon profil santé » permet à l’utilisateur de personnaliser l’affichage et le tri des produits en fonction de son profil (objectif nutritionnel et contraintes de santé). 

Une fois le profil défini et le tri personnalisé activé, l’application :
- calcule un **score santé personnalisé** pour chaque produit,
- réorganise les produits du Dashboard pour mettre en avant ceux qui sont **les plus adaptés** au profil de l’utilisateur (par exemple, réduction du sucre pour un utilisateur diabétique).

---

## 2. Localisation dans l’application

- Page : **« Mon profil santé »** dans le menu latéral Streamlit.
- Fichiers principaux :
  - `streamlit_app/health_profile.py` :
    - définition du modèle `HealthProfile`,
    - logique de calcul du score personnalisé (`compute_personalized_scores`),
    - interface de configuration du profil (`show_health_profile_page`).
  - `streamlit_app/main.py` :
    - prise en compte du profil pour trier les produits sur le Dashboard,
    - bouton d’activation/désactivation du tri personnalisé.

---

## 3. Contenu du profil santé

Le profil santé est représenté par la classe `HealthProfile` avec deux éléments principaux :

- **Objectif principal** (goal) :
  - `equilibree` : Alimentation équilibrée,
  - `perte_poids` : Perte de poids,
  - `reduire_sucre` : Réduction du sucre,
  - `reduire_sel` : Réduction du sel.

- **Contraintes de santé** (constraints) :
  - `diabete` : Diabète (limiter le sucre),
  - `hypertension` : Hypertension (limiter le sel).

Ces informations sont utilisées pour ajuster les pondérations dans le calcul du score santé personnalisé.

---

## 4. Logique de sélection des objectifs

Sur la page « Mon profil santé », l’utilisateur commence par sélectionner ses **contraintes de santé**. En fonction de ces contraintes :

- Si l’utilisateur coche **« Diabète (limiter sucre) »** :
  - l’objectif **« Réduction du sucre »** est automatiquement privilégié,
  - l’option « Réduction du sel » peut être masquée pour éviter une confusion,
  - les objectifs généraux comme « Alimentation équilibrée » et « Perte de poids » restent disponibles.

- Si l’utilisateur coche **« Hypertension (limiter sel) »** :
  - l’objectif **« Réduction du sel »** est automatiquement privilégié,
  - l’option « Réduction du sucre » peut être masquée,
  - là aussi, les objectifs généraux restent disponibles.

- Si aucune contrainte n’est sélectionnée :
  - tous les objectifs sont proposés librement.

Cette logique permet de **guider l’utilisateur** vers un objectif cohérent avec ses contraintes, tout en lui laissant la possibilité d’affiner son objectif.

---

## 5. Activation / désactivation du tri personnalisé

Une fois le profil renseigné, l’utilisateur peut activer le tri personnalisé via un bouton :

- Sur la page **« Mon profil santé »** :
  - Bouton : « Voir des alternatives plus saines pour moi » / « Désactiver les recommandations personnalisées ».
- Sur le **Dashboard** (page principale) :
  - Le même bouton est visible sous les filtres pour permettre d’activer/désactiver rapidement le tri personnalisé.

Lorsque le tri personnalisé est **activé** :
- un message s’affiche : « Tri personnalisé activé en fonction de votre profil santé. »,
- les produits sont triés en fonction du **score santé personnalisé**.

Lorsque le tri est **désactivé** :
- l’application revient à un tri classique (NutriScore, sucre ou sel selon le choix de l’utilisateur).

---

## 6. Principe du score santé personnalisé

### 6.1. Variables prises en compte

Pour chaque produit, les variables utilisées sont :

- le **NutriScore** (A à E),
- la **teneur en sucre** (sucre_100g),
- la **teneur en sel** (sel_100g).

Le NutriScore est converti en score numérique :
- A → 5,
- B → 4,
- C → 3,
- D → 2,
- E → 1.

### 6.2. Formule générale

Le score final est de la forme :

- \( S = \alpha \times score_{nutri} + \beta \times sucre_{100g} + \gamma \times sel_{100g} \)

avec :

- \( \alpha > 0 \) : coefficient positif qui favorise les bons NutriScore,
- \( \beta < 0 \) : coefficient négatif qui pénalise le sucre élevé,
- \( \gamma < 0 \) : coefficient négatif qui pénalise le sel élevé.

Les coefficients \( \alpha, \beta, \gamma \) sont ajustés en fonction :

- de l’**objectif principal** :
  - « Réduction du sucre » renforce la pénalisation du sucre (\( \beta \) plus négatif),
  - « Réduction du sel » renforce la pénalisation du sel (\( \gamma \) plus négatif),
  - « Alimentation équilibrée » garde un équilibre entre NutriScore, sucre et sel,
  - « Perte de poids » peut donner un poids plus fort au NutriScore global.

- des **contraintes** :
  - diabète → renforce encore \( \beta \),
  - hypertension → renforce encore \( \gamma \).

### 6.3. Nettoyage des données

Avant le calcul :
- les valeurs de sucre/sel **aberrantes** (négatives ou totalement hors plage raisonnable) sont remplacées par `NaN`,
- certaines valeurs sont ramenées à l’échelle (par exemple, si 100 × plus grandes que prévu, elles sont divisées par 100),
- cela évite qu’une erreur de saisie ne fausse le score.

---

## 7. Impact sur le Dashboard

### 7.1. Tri des résultats

Sur la page principale (Dashboard) :

1. L’utilisateur applique ses filtres habituels (nom, catégorie, NutriScore, sucre max, etc.).
2. L’application récupère les produits correspondants.
3. Si un profil santé est défini et que le tri personnalisé est activé :
   - `compute_personalized_scores` calcule un score pour chaque produit,
   - les produits sont triés **du meilleur au moins bon** selon ce score,
   - le tri choisi (NutriScore, sucre ou sel) reste visible, mais l’ordre tient compte du score personnalisé.

### 7.2. Vue d’accueil

- Lorsque l’utilisateur arrive sur le Dashboard **sans filtre particulier** (vue d’accueil) :
  - si le tri personnalisé est désactivé, l’application affiche un **échantillon aléatoire** de produits, en privilégiant ceux avec image,
  - si le tri personnalisé est **activé**, l’application affiche directement les **10 meilleurs produits** selon le profil santé.

---

## 8. Exemple d’utilisation (résumé)

1. L’utilisateur se rend dans **« Mon profil santé »**.
2. Il coche une contrainte (ex. diabète) et choisit ou confirme l’objectif (ex. réduction du sucre).
3. Il enregistre le profil et active le tri personnalisé.
4. De retour sur le Dashboard, il applique ses filtres (catégorie, NutriScore, sucre max).
5. Les produits sont présentés dans un ordre qui tient compte :
   - du NutriScore,
   - du sucre et du sel,
   - de son objectif et de ses contraintes.

Cette fonctionnalité apporte une **dimension personnalisée** à la recommandation de produits, au-delà des simples filtres.
