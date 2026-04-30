from datetime import datetime
from .config import ENABLE_LOGGING


# =========================
# 🪵 LOG PRINCIPAL
# =========================
def log(message):
    """
    Log simple avec timestamp
    """

    if not ENABLE_LOGGING:
        return

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[INGREDIENTS_AI] [{timestamp}] {message}")


# =========================
# ⚠️ WARNING
# =========================
def warn(message):
    if not ENABLE_LOGGING:
        return

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[WARNING] [{timestamp}] {message}")


# =========================
# ❌ ERROR
# =========================
def error(message):
    if not ENABLE_LOGGING:
        return

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[ERROR] [{timestamp}] {message}")


# =========================
# 📊 DEBUG (optionnel)
# =========================
def debug(message):
    if not ENABLE_LOGGING:
        return

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[DEBUG] [{timestamp}] {message}")