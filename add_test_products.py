import pandas as pd

CSV_PATH = "data/sample_products_clean.csv"

TEST_CODES = [
    ("3017620422003", "Nutella"),
    ("7622210449283", "Oreo"),
    ("5449000000996", "Coca-Cola"),
]

df = pd.read_csv(
    CSV_PATH,
    dtype=str,
    keep_default_na=False,
    engine="python",
    on_bad_lines="skip"
)

def make_row(code, name):
    row = {col: "" for col in df.columns}
    row["code"] = code
    if "product_name" in row:
        row["product_name"] = name
    if "brands" in row:
        row["brands"] = "Test OpenFoodFacts"
    if "categories" in row:
        row["categories"] = "Test"
    if "categories_tags" in row:
        row["categories_tags"] = "en:test"
    if "ingredients_text" in row:
        row["ingredients_text"] = "Produit de test pour images OpenFoodFacts"
    return row

existing = set(df["code"].astype(str))
rows = []

for code, name in TEST_CODES:
    if code not in existing:
        rows.append(make_row(code, name))

if rows:
    df = pd.concat([pd.DataFrame(rows), df], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)
    print("✅ Produits test ajoutés")
else:
    print("ℹ️ Produits déjà présents")
