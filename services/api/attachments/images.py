"""Validate and normalize uploaded images (REQ-032).

Every accepted image is decoded and re-encoded, so what is stored is a real image of bounded size with no
metadata: phone photos carry GPS position in EXIF, and player location must never be exposed (REQ-006).
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
ACCEPTED_FORMATS = ["JPEG", "PNG", "WEBP"]
OUTPUT_CONTENT_TYPE = "image/webp"


def normalize_image(upload, *, max_side: int) -> bytes:
    """WebP bytes of `upload`, turned upright and scaled to fit `max_side`. Raises ValidationError with a
    message for the person uploading."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError({"file": "Choose an image under 5 MB."})
    try:
        with Image.open(upload, formats=ACCEPTED_FORMATS) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValidationError({"file": "That image is too large. Choose a smaller one."})
            image = ImageOps.exif_transpose(image)
            image.thumbnail((max_side, max_side))
            transparent = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if transparent else "RGB")
            out = BytesIO()
            image.save(out, "WEBP", quality=85)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError({"file": "Choose a JPEG, PNG or WebP image."}) from None
    return out.getvalue()
