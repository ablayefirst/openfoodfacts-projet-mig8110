from openai import OpenAI
import psycopg2
import json
import os
from openai import OpenAI

# 🔐 1. Connexion LLM
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 🗄️ DB
conn = psycopg2.connect(
    host="localhost",
    database="openfood_db",
    user="postgres",
    password="postgres123"
)
cursor = conn.cursor()

# 📥 Récupérer ingrédients
cursor.execute("""
    SELECT DISTINCT ingredients_nom
    FROM ingredient
""")

rows = cursor.fetchall()

# ✔ créer liste
ingredients_raw = [row[0] for row in rows if row[0]]

# ✔ nettoyer
ingredients = list(set(i.lower().strip() for i in ingredients_raw))

# 🔄 batch
def chunk_list(lst, size=20):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

# 🚀 traitement
for batch in chunk_list(ingredients, 20):

    prompt = f"""
Tu es un expert en nutrition.

Pour chaque ingrédient donné :

1. Donne un nom standard en français (ingredient_standard)
2. Garde le nom original comme synonyme

IMPORTANT :
- Ne regroupe pas
- Traite chaque ingrédient séparément
- Le synonyme doit rester EXACT

Retourne JSON :

[
  {{
    "ingredient_standard": "...",
    "synonyme": "..."
  }}
]

Liste : {batch}
"""

    

    response = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}]
    )

    content = response.choices[0].message.content

    try:
        data = json.loads(content)
    except:
        print("Erreur parsing JSON")
        continue

    # 💾 insertion
    for group in data:
        standard = group["ingredient_standard"]
        synonym = group["synonyme"]

        cursor.execute("""
            INSERT INTO ingredient (ingredients_nom)
            VALUES (%s)
            ON CONFLICT (ingredients_nom) DO NOTHING
            RETURNING id_ingredient
        """, (standard,))
        
        result = cursor.fetchone()

        if result:
            ingredient_id = result[0]
        else:
            cursor.execute(
                "SELECT id_ingredient FROM ingredient WHERE ingredients_nom = %s",
                (standard,)
            )
            ingredient_id = cursor.fetchone()[0]

        
            cursor.execute("""
                INSERT INTO synonyme_ingredient (nom_synonyme, id_ingredient)
                VALUES (%s, %s)
            """, (synonym, ingredient_id))

    conn.commit()

print("✅ Synonymes générés avec succès")

cursor.close()
conn.close()