from sentence_transformers import SentenceTransformer, util
import torch

from .config import EMBEDDING_THRESHOLD
from .logger import log


class EmbeddingCorrector:
    """
    Corrige les ingrédients via similarité sémantique
    et retourne aussi le nombre d'ingrédients reconnus
    """

    def __init__(self, reference_list, threshold=EMBEDDING_THRESHOLD):
        log("🔄 Initializing embedding corrector...")

        self.threshold = threshold

        # 🔥 normalisation références
        self.reference_list = [
            str(r).lower().strip()
            for r in reference_list
            if isinstance(r, str) and r.strip()
        ]

        # 🔥 lazy loading
        self.model = None
        self.reference_embeddings = None

        if not self.reference_list:
            log("⚠️ No reference data → embedding disabled")

    # =========================
    # 🔥 LAZY LOAD MODEL
    # =========================
    def _load_model(self):

        if self.model is not None:
            return

        if not self.reference_list:
            return

        log("🔄 Lazy loading embedding model...")

        try:
            self.model = SentenceTransformer("all-MiniLM-L6-v2")

            log(f"📊 Encoding {len(self.reference_list)} reference synonyms...")

            self.reference_embeddings = self.model.encode(
                self.reference_list,
                convert_to_tensor=True
            )

            log("✅ Embedding model ready")

        except Exception as e:
            log(f"❌ Failed to load embedding model: {e}")
            self.model = None
            self.reference_embeddings = None

    # =========================
    # 🔧 CORRECTION + SCORE
    # =========================
    def correct(self, ingredients):
        """
        Retourne:
            corrected: liste corrigée
            match_count: nombre d'ingrédients reconnus
        """

        if not ingredients:
            return [], 0

        # 🔥 lazy load ici
        self._load_model()

        if self.model is None or self.reference_embeddings is None:
            return ingredients, 0

        # 🔥 normalisation entrée
        ingredients = [
            str(ing).lower().strip()
            for ing in ingredients
            if isinstance(ing, str) and ing.strip()
        ]

        try:
            ing_embeddings = self.model.encode(
                ingredients,
                convert_to_tensor=True
            )

            scores = util.cos_sim(ing_embeddings, self.reference_embeddings)

            max_scores, best_indices = scores.max(dim=1)

            corrected = []
            match_count = 0

            for i, ing in enumerate(ingredients):

                if max_scores[i].item() >= self.threshold:
                    corrected.append(self.reference_list[best_indices[i]])
                    match_count += 1
                else:
                    corrected.append(ing)

        except Exception as e:
            log(f"❌ Embedding error: {e}")
            return ingredients, 0

        return corrected, match_count

    # =========================
    # 🧠 CHECK
    # =========================
    def is_all_known(self, ingredients):

        if not ingredients:
            return False

        corrected, match_count = self.correct(ingredients)

        return match_count == len(corrected)