# 🔐 Espace Administrateur

L’application contient un espace administrateur protégé permettant :

- Connexion sécurisée
- Accès à la liste des produits
- Ajout / modification / suppression de produits
- Gestion complète via interface web

---

## 📍 Routes Admin

- `/admin/login` → Page de connexion
- `/admin/logout` → Déconnexion
- `/admin/products` → Liste des produits (protégé)
- `/admin/product/new` → Ajouter un produit
- `/admin/product/{code}/edit` → Modifier un produit
- `/admin/product/{code}/delete` → Supprimer un produit

---

## 🔑 Configuration des identifiants Admin

Avant de lancer l’application, définir :

### Windows PowerShell :

```powershell
$env:ADMIN_USER="admin"
$env:ADMIN_PASSWORD="admin123"
$env:SECRET_KEY="change_this_secret"
🗄 Configuration Base de Données

Définir la variable de connexion PostgreSQL :

$env:DATABASE_URL="postgresql+psycopg://postgres:admin@localhost:5432/openfoodfacts_canada"

⚠️ Si votre base contient un espace à la fin :

$env:DATABASE_URL="postgresql+psycopg://postgres:admin@localhost:5432/openfoodfacts_canada%20"
🚀 Comment lancer l’application
1️⃣ Activer l’environnement virtuel
.\.venv\Scripts\activate
2️⃣ Installer les dépendances (si pas encore fait)
pip install -r requirements.txt
3️⃣ Lancer le serveur
uvicorn app.main:app --reload
🌍 Accès

Accueil :

http://127.0.0.1:8000/

Connexion Admin :

http://127.0.0.1:8000/admin/login
👤 Identifiants par défaut
Champ	Valeur
Username	admin
Password	admin123

L’application est maintenant prête à être utilisée.