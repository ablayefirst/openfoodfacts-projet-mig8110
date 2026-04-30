import os
import base64

_NO_IMAGE_DATA_URI = None


def get_no_image_data_uri() -> str:
    """Retourne un data URI base64 pour l'image par défaut no_image.png.

    L'image est lue une seule fois puis mise en cache en mémoire.
    """
    global _NO_IMAGE_DATA_URI
    if _NO_IMAGE_DATA_URI is not None:
        return _NO_IMAGE_DATA_URI

    try:
        no_image_path = os.path.join(
            os.path.dirname(__file__),
            "static",
            "Image_app",
            "no_image.png",
        )
        with open(no_image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        _NO_IMAGE_DATA_URI = f"data:image/png;base64,{encoded}"
    except Exception:
        _NO_IMAGE_DATA_URI = ""

    return _NO_IMAGE_DATA_URI