from .logger import log


def load_synonyms_from_db(engine):
    """
    Nouveau comportement :
    - reference_list = DISTINCT nom_ingredient_brut
    - synonym_map    = {nom_ingredient_brut → nom_canonique}

    L'embedding cherche le brut le plus proche,
    puis synonym_map retourne le canonique correspondant.
    """

    query_bruts = """
    SELECT DISTINCT
        nom_ingredient_brut,
        nom_canonique
    FROM ingredient_standardise
    WHERE nom_ingredient_brut IS NOT NULL
      AND TRIM(nom_ingredient_brut) != ''
      AND nom_canonique IS NOT NULL
    """

    synonym_map = {}

    try:
        with engine.connect() as conn:
            result = conn.execution_options(
                stream_results=True
            ).execute(query_bruts)

            for row in result:
                try:
                    brut      = str(row[0]).lower().strip()
                    canonique = str(row[1]).lower().strip()
                    if not brut or not canonique:
                        continue
                    synonym_map[brut] = canonique
                except Exception:
                    continue

        if not synonym_map:
            log("⚠️ No ingredients bruts found in DB (first run likely)")
        else:
            log(f"✅ {len(synonym_map)} ingrédients bruts chargés comme référence embedding")

        return synonym_map

    except Exception as e:
        log(f"❌ Error loading ingredients bruts: {e}")
        return {}