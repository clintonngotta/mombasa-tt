"""Validate and normalize uploaded images (REQ-032).

Every accepted image is decoded and re-encoded, so what is stored is a real image of bounded size with no
metadata: phone photos carry GPS position in EXIF, and player location must never be exposed (REQ-006).
"""

from io import BytesIO

from PIL import Image, ImageOps
from rest_framework.exceptions import ValidationError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Decoding costs about four bytes a pixel whatever the file size, so this bounds memory per upload.
MAX_PIXELS = 25_000_000
ACCEPTED_FORMATS = ["JPEG", "PNG", "WEBP"]
OUTPUT_CONTENT_TYPE = "image/webp"
NOT_AN_IMAGE = "Choose a JPEG, PNG or WebP image."


def normalize_image(upload, *, max_side: int) -> bytes:
    """WebP bytes of `upload`, turned upright and scaled to fit `max_side`. Raises ValidationError with a
    message for the person uploading."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError({"file": "Choose an image under 5 MB."})
    try:
        with Image.open(upload, formats=ACCEPTED_FORMATS) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValidationError({"file": "That image has too many pixels. Choose a smaller one."})
            # Let the JPEG decoder shrink while it reads, then scale before turning upright, so the
            # full-size picture is held in memory once at most.
            image.draft("RGB", (max_side * 2, max_side * 2))
            image.thumbnail((max_side, max_side))
            image = ImageOps.exif_transpose(image)
            transparent = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if transparent else "RGB")
            out = BytesIO()
            image.save(out, "WEBP", quality=85)
    except ValidationError:
        raise
    except Exception:
        # Pillow raises many different errors on damaged files (SyntaxError, struct.error, OSError...).
        # Whatever it was, the upload isn't an image we can use.
        raise ValidationError({"file": NOT_AN_IMAGE}) from None
    return out.getvalue()
