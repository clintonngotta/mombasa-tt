"""File names for what the API hands out to save: named after what they show, not after the app."""

import re

from django.http import HttpResponse
from django.utils.http import content_disposition_header

# Characters that break a file name on some system, and runs of spaces.
UNSAFE = re.compile(r'[\x00-\x1f\x7f"*/:<>?\\|]+')
SPACES = re.compile(r"\s+")
MAX_STEM = 150


def file_name(*parts: str, extension: str) -> str:
    """`Coast Open 2026 - Men's Singles - Draw.pdf`: the non-empty parts joined, made safe to save."""
    cleaned = [SPACES.sub(" ", UNSAFE.sub(" ", part)).strip(" .") for part in parts]
    stem = " - ".join(part for part in cleaned if part)[:MAX_STEM].strip(" .-") or "Coast TT"
    return f"{stem}.{extension}"


def named(response: HttpResponse, name: str, *, attachment: bool) -> HttpResponse:
    """Give `response` its file name, quoted for every browser (non-ASCII names included)."""
    response["Content-Disposition"] = content_disposition_header(attachment, name)
    return response
