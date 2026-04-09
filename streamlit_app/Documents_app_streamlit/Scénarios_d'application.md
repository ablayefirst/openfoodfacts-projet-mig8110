## 3. Scénarios d’application

### Scénario 1 – Utilisateur grand public (profil santé + comparaison)

**Contexte**  
soit l'utlisatrice Marie, 45 ans, est suivie pour un début de diabète. Elle souhaite choisir des produits du quotidien plus adaptés à sa situation (moins sucrés), sans entrer dans des détails techniques compliqués.

**Étapes du scénario**

1. **Ouverture de l’application**  
  - Marie lance l’application dans son navigateur via l’URL locale (par ex. `http://localhost:8501`).  
  - La page **Dashboard** s’affiche avec la liste des produits.

2. **Configuration de son profil santé**  
  - Dans le menu latéral, elle clique sur **« Mon profil santé »**.  
  - Dans la section *Contraintes de santé*, elle coche **« Diabète (limiter sucre) »**.  
  - L’application lui propose automatiquement l’objectif **« Réduction du sucre »** comme objectif principal.  
  - Elle peut éventuellement conserver ou ajuster cet objectif (par exemple ajouter « Alimentation équilibrée »).  
  - Elle clique sur **« Enregistrer mon profil »**.  
  - Elle active ensuite le bouton **« Voir des alternatives plus saines pour moi »** pour activer le tri personnalisé.

3. **Retour au Dashboard et exploration des produits**  
  - Marie revient sur la page **Dashboard** (option « Dashboard » dans le menu).  
  - Elle saisit par exemple *"céréales"* dans la barre de recherche ou limite la **catégorie principale** à *"céréales"* si cette catégorie existe.  
  - Elle conserve le filtre NutriScore sur A–C et un **sucre max** raisonnable (par exemple 30 g/100 g).  
  - Le tri est réglé sur **« NutriScore (A→E) »** ou sur **« Sucre (g/100g) »** selon ce qu’elle souhaite prioriser.  
  - Grâce à son profil santé actif, les produits sont automatiquement triés pour mettre en avant ceux qui combinent **bon NutriScore** et **faible teneur en sucre**.

4. **Sélection de produits pour comparaison**  
  - Sur les cartes produits, Marie coche la case **« Comparer »** pour 3 produits qui l’intéressent.  
  - Un message lui rappelle qu’elle ne peut sélectionner **au maximum que 3 produits** à la fois.  
  - Le compteur au-dessus de la liste indique le nombre de produits sélectionnés pour la comparaison.

5. **Utilisation du comparateur**  
  - Elle clique sur le bouton **« Comparer les produits sélectionnés »**.  
  - L’application l’emmène sur la page **Comparateur de produits**.  
  - Les 2 à 3 produits sont affichés **côte à côte** avec : NutriScore, NOVA, sucre, sel, graisses saturées, fibres, protéines.  
  - Comme son profil santé est actif, un **score personnalisé** est calculé pour chaque produit et la section *« Meilleur choix parmi ces produits »* met en avant celui qui répond le mieux à son profil (diabète → réduction du sucre).  
  - Marie peut ainsi choisir plus facilement le produit le plus adapté.

6. **Consultation du détail d’un produit**  
  - Si elle souhaite en savoir davantage, elle clique sur **« Détails »** depuis le Dashboard sur un produit donné.  
  - La page **Détail produit** s’ouvre avec : informations complètes, valeurs nutritionnelles détaillées, ingrédients, allergènes, labels.  
  - Un bouton **« Retour au Dashboard »** lui permet de revenir à la liste des produits.

7. **Exploration des tendances globales**  
  - Enfin, Marie consulte la page **« Tendances »** pour avoir une vision globale : répartition des NutriScore, catégories les plus sucrées, etc.  
  - Elle peut filtrer les analyses pour se concentrer, par exemple, sur les produits de petit-déjeuner.

**Résultat attendu**  
À la fin de ce scénario, Marie a :

- configuré un **profil santé personnalisé**,
- obtenu un **tri intelligent** des produits en fonction de son diabète,
- utilisé le **comparateur** pour choisir le meilleur produit parmi plusieurs options,
- consulté des **statistiques globales** pour mieux comprendre l’offre de produits.

---

### Scénario 2 – Administrateur (gestion du catalogue produits)

**Contexte**  
Alex est administrateur de la base de données OpenFoodFacts Canada utilisée par l’application. Il souhaite corriger un produit mal renseigné et ajouter une nouvelle référence.

**Étapes du scénario**

1. **Accès à l’interface Admin**  
  - Alex lance l’application Streamlit et accède à `http://localhost:8501`.  
  - Dans le menu latéral, il sélectionne **« Admin »**.  
  - Il saisit ses identifiants d’administration (définis via `ADMIN_USER` et `ADMIN_PASSWORD`).

2. **Recherche d’un produit existant**  
  - Dans la liste paginée, il utilise les champs de recherche pour filtrer par **code produit**, **nom** ou **marque**.  
  - Il identifie le produit à corriger (par exemple une boisson dont le NutriScore ou les catégories sont incorrects).

3. **Modification d’un produit**  
  - Il ouvre la fiche du produit et modifie :
    - la marque,
    - la catégorie principale ou les catégories associées,
    - les valeurs nutritionnelles (sucre, sel, etc.) si nécessaire.  
  - Il enregistre les modifications, qui sont immédiatement répercutées dans la base PostgreSQL.

4. **Ajout d’un nouveau produit**  
  - Alex clique sur **« Ajouter un produit »**.  
  - Il renseigne les champs obligatoires (code produit, nom, marque, catégories, valeurs nutritionnelles).  
  - Il associe les ingrédients et éventuels allergènes via les tables d’association.  
  - Il enregistre le nouveau produit.

5. **Vérification côté utilisateur**  
  - Alex revient sur la page **Dashboard** en tant qu’utilisateur standard.  
  - Il recherche le produit qu’il vient de créer ou de modifier pour vérifier que :
    - la fiche apparaît correctement,
    - les valeurs nutritionnelles sont bien prises en compte dans le tri et dans le profil santé,
    - le produit est disponible dans le comparateur.

**Résultat attendu**  
À la fin de ce scénario, Alex a :

- corrigé des données erronées,
- enrichi le catalogue avec un **nouveau produit**,
- vérifié l’impact de ces changements sur l’expérience utilisateur (recherche, profil santé, comparaison).

Ces deux scénarios peuvent être directement repris dans un document Word (copier/coller) pour illustrer l’usage de l’application dans un rapport ou une soutenance.