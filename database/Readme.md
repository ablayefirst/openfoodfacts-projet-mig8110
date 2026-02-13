
#  Configuration de la Connexion PostgreSQL (SQLTools dans VSCode)

établir une connexion entre Visual Studio Code et la base de données PostgreSQL à l’aide de l’extension **SQLTools**.

---

## Les Étapes

### 1️ Installer l’extension

Dans VSCode :

* Aller dans Extensions
* Rechercher : `SQLTools`
* Installer :

  * SQLTools
  * SQLTools PostgreSQL Driver

---

### 2️ Ajouter une nouvelle connexion

Dans VSCode ou dans ton votre environnement(outil) de travail:

1. Ouvrir SQLTools
2. Cliquer sur **Add New Connection**
3. Sélectionner **PostgreSQL**

---

### 3️ Paramètres de connexion

| Champ           | Valeur                   |
| --------------- | ------------------------ |
| Connection name | PostgreSQL OpenFoodFacts |
| Driver          | PostgreSQL               |
| Conection group | (vide) ou OpenFoodFacts  |
| Server          | localhost                |
| Port            | 5432                     |
| Database        | openfoodfacts_canada     |
| Username        | postgres                 |
| Password        | admin                    |

---

### 4 Tester la connexion

Cliquer sur **Test Connection**.

Si tout est correct :

✔ Connexion réussie
✔ La base apparaît dans SQLTools

---

##  Informations importantes

* PostgreSQL est installé localement.
* Le port par défaut PostgreSQL est `5432`.
* La base `openfoodfacts_canada` doit déjà être créée dans PostgreSQL:


---

##  Exécution du script SQL

Une fois connecté :

1. Ouvrir le fichier `create_tables.sql`
2. Clic droit → Run Query
3. Vérifier la création des tables

---

 L’environnement de développement a été configuré sous Visual Studio Code en utilisant l’extension SQLTools afin de permettre une gestion centralisée des requêtes SQL et une connexion sécurisée à PostgreSQL.

---




