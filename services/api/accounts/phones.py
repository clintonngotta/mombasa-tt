"""Phone numbers as players type them, stored in E.164 (+254712345678).

Numbers without a country code are read as Kenyan, where Coast TT starts: 0712 345 678 and
712 345 678 both mean +254 712 345 678. Anything with a leading + or 00 keeps its own code.
"""

import re

DEFAULT_COUNTRY_CODE = "254"
_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_phone(raw: str) -> str | None:
    """The number in E.164, or None if it can't be a phone number."""
    text = _SEPARATORS.sub("", raw or "")
    if text.startswith("+"):
        digits = text[1:]
    elif text.startswith("00"):
        digits = text[2:]
    elif text.startswith("0"):
        digits = DEFAULT_COUNTRY_CODE + text[1:]
    elif text.startswith(DEFAULT_COUNTRY_CODE) and len(text) == 12:
        digits = text
    elif len(text) == 9:
        digits = DEFAULT_COUNTRY_CODE + text
    else:
        return None
    if not digits.isdigit() or digits.startswith("0") or not 8 <= len(digits) <= 15:
        return None
    if digits.startswith(DEFAULT_COUNTRY_CODE) and len(digits) != 12:
        return None  # Kenyan numbers have nine digits after the code
    return "+" + digits


def looks_like_phone(text: str) -> bool:
    """A sign-in name with no @ and mostly digits is a phone number, not an email address."""
    return "@" not in text and sum(ch.isdigit() for ch in text) >= 7
