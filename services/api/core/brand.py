"""The Coast Loopas look for files the app makes (PDFs and share images): the logo, the brand colours of
the web app (apps/web/src/index.css) and its heading typeface, Barlow Condensed (SIL Open Font License,
core/brand/OFL.txt).

Images are PNG, drawn with Pillow, so they open and share everywhere (WhatsApp won't share an SVG). An
image is a stack of cards under a navy header with the logo, sized to what it holds.
"""

import io
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent / "brand"
LOGO = ASSETS / "logo-primary.png"  # for light backgrounds
LOGO_REVERSED = ASSETS / "logo-reversed.png"  # for navy
LOGO_MARK = ASSETS / "logo-mark.png"
SITE = "coastloopas.org"

NAVY = "#031539"
BLUE = "#024385"
GOLD = "#ffd859"
CYAN = "#08b8f0"
SKY = "#eef5fb"  # page behind the cards
LINE = "#d9e3ee"
INK = "#031539"
MUTED = "#5b6b80"
WHITE = "#ffffff"
SILVER = "#cfd8e3"
BRONZE = "#e2a66b"
MEDAL = {1: GOLD, 2: SILVER, 3: BRONZE}


def font_path(weight: int, extended: bool = False) -> Path:
    """Barlow Condensed at 400, 600 or 700. The main file covers Latin-1 and the common punctuation; the
    extended one the rest of the Latin letters (ũ and ĩ in Kikuyu names, for one)."""
    return ASSETS / f"BarlowCondensed-{'ext-' if extended else ''}{weight}.ttf"


@cache
def _covered(extended: bool) -> frozenset[int]:
    from reportlab.pdfbase.ttfonts import TTFontFile

    return frozenset(TTFontFile(str(font_path(400, extended))).charToGlyph)


def runs(text: str) -> list[tuple[str, bool]]:
    """The text in runs of (characters, from the extended file?): a character the main file lacks and the
    extended one has comes from the extended one."""
    found: list[tuple[str, bool]] = []
    main, extended = _covered(False), _covered(True)
    for ch in text:
        ext = ord(ch) not in main and ord(ch) in extended
        if found and found[-1][1] == ext:
            found[-1] = (found[-1][0] + ch, ext)
        else:
            found.append((ch, ext))
    return found


class Face:
    """Barlow Condensed at one weight and size, measuring and drawing across both files."""

    def __init__(self, weight: int, size: int):
        self.fonts = {ext: ImageFont.truetype(str(font_path(weight, ext)), size) for ext in (False, True)}

    def getlength(self, text: str) -> float:
        return sum(self.fonts[ext].getlength(part) for part, ext in runs(text))

    def draw(
        self, draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fill: str, anchor: str = "la"
    ) -> None:
        x, y = xy
        width = self.getlength(text)
        x -= {"l": 0, "m": width / 2, "r": width}[anchor[0]]
        for part, ext in runs(text):
            draw.text((x, y), part, font=self.fonts[ext], fill=fill, anchor="l" + anchor[1])
            x += self.fonts[ext].getlength(part)


@cache
def _font(weight: int, size: int) -> Face:
    return Face(weight, size)


@cache
def _logo(path: Path, height: int) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    return image.resize((round(image.width * height / image.height), height), Image.LANCZOS)


def fit(text: str, font: Face, width: float) -> str:
    """The text cut with an ellipsis so it fits `width` pixels."""
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(text: str, font: Face, width: float) -> list[str]:
    """The text broken into lines no wider than `width` pixels, at spaces where it can."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if font.getlength(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = fit(word, font, width)
        lines.append(line)
    return lines


@dataclass
class Row:
    """One line of a card. `badge` is a place (1, 2, 3 get medal colours) or a short label; `aside` sits on
    the right (a club, a score); `strong` marks a winner."""

    text: str
    aside: str = ""
    badge: int | str | None = None
    strong: bool = False
    note: bool = False  # a small muted line (a round's name, the games of a match)


@dataclass
class Card:
    title: str
    rows: list[Row] = field(default_factory=list)
    big: bool = False  # bigger type, for a card with a few rows (a match result)


WIDTH = 1080
PAD = 56
HEADER = 330
FOOTER = 96
MAX_HEIGHT = 4000
ROW_H = {False: 68, True: 104}
NOTE_H = 46


def _row_height(row: Row, big: bool) -> int:
    return NOTE_H if row.note else ROW_H[big]


def _card_height(card: Card) -> int:
    return 92 + sum(_row_height(row, card.big) for row in card.rows) + 24


def share_image(title: str, subtitle: str, cards: list[Card], footnote: str = "") -> bytes:
    """A PNG 1080 wide: the logo and title on navy, the cards on a light page, the site at the foot. Cards
    that would make it taller than MAX_HEIGHT are left out, and the footnote says how many."""
    shown: list[Card] = []
    height = HEADER + 40 + FOOTER
    for card in cards:
        extra = _card_height(card) + 28
        if height + extra > MAX_HEIGHT:
            break
        shown.append(card)
        height += extra
    left_out = len(cards) - len(shown)
    if left_out:
        footnote = f"…and {left_out} more in the full results. {footnote}".strip()
    if footnote:
        height += 56
    height = max(height, WIDTH)

    image = Image.new("RGB", (WIDTH, height), SKY)
    draw = ImageDraw.Draw(image)
    _header(image, draw, title, subtitle)

    y = HEADER + 40
    for card in shown:
        y = _draw_card(draw, card, y) + 28
    if footnote:
        _font(600, 30).draw(draw, (PAD, y + 4), fit(footnote, _font(600, 30), WIDTH - 2 * PAD), MUTED)

    top = height - FOOTER
    draw.rectangle((0, top, WIDTH, height), fill=NAVY)
    draw.rectangle((0, top, WIDTH, top + 8), fill=GOLD)
    _font(700, 36).draw(draw, (PAD, top + 28), SITE, WHITE)
    _font(600, 32).draw(draw, (WIDTH - PAD, top + 30), "COAST TABLE TENNIS", CYAN, "ra")

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _header(image: Image.Image, draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, HEADER), fill=NAVY)
    logo = _logo(LOGO_REVERSED, 150)
    image.paste(logo, (PAD, 36), logo)
    heading = wrap(title.upper(), _font(700, 60), WIDTH - 2 * PAD)[:2]
    if len(heading) == 2:
        heading = [heading[0], fit(heading[1], _font(700, 60), WIDTH - 2 * PAD)]
    size = 60 if len(heading) == 1 else 48
    y = 200 if len(heading) == 1 else 196
    for line in heading:
        _font(700, size).draw(draw, (PAD, y), fit(line, _font(700, size), WIDTH - 2 * PAD), WHITE)
        y += size + 4
    if subtitle:
        _font(600, 32).draw(draw, (PAD, y + 4), fit(subtitle, _font(600, 32), WIDTH - 2 * PAD), GOLD)
    draw.rectangle((0, HEADER - 10, WIDTH, HEADER), fill=CYAN)


def _draw_card(draw: ImageDraw.ImageDraw, card: Card, top: int) -> int:
    bottom = top + _card_height(card)
    draw.rounded_rectangle(
        (PAD - 16, top, WIDTH - PAD + 16, bottom), radius=24, fill=WHITE, outline=LINE, width=2
    )
    draw.rounded_rectangle((PAD - 16, top, PAD - 4, top + 92), radius=6, fill=GOLD)
    _font(700, 44).draw(
        draw, (PAD + 16, top + 24), fit(card.title.upper(), _font(700, 44), WIDTH - 2 * PAD - 32), BLUE
    )
    y = top + 92
    left, right = PAD + 16, WIDTH - PAD - 16
    for index, row in enumerate(card.rows):
        h = _row_height(row, card.big)
        if index and not row.note and not card.rows[index - 1].note:
            draw.line((left, y, right, y), fill=LINE, width=2)
        if row.note:
            _font(600, 28).draw(draw, (left, y + 8), fit(row.text, _font(600, 28), right - left), MUTED)
            y += h
            continue
        size = 56 if card.big else 36
        x = left
        if row.badge is not None:
            r = 30 if card.big else 24
            cx, cy = left + r, y + h // 2
            fill = MEDAL.get(row.badge, SKY) if isinstance(row.badge, int) else SKY
            draw.ellipse(
                (cx - r, cy - r, cx + r, cy + r),
                fill=fill,
                outline=NAVY if isinstance(row.badge, int) and row.badge in MEDAL else LINE,
                width=2,
            )
            _font(700, r + 6).draw(draw, (cx, cy), str(row.badge), NAVY, "mm")
            x = left + 2 * r + 20
        aside_font = _font(700 if card.big else 600, 64 if card.big else 30)
        aside_w = aside_font.getlength(row.aside) if row.aside else 0
        aside_w = min(aside_w, (right - x) * 0.45)
        text_font = _font(700 if row.strong or card.big else 600, size)
        colour = BLUE if row.strong else INK
        text_font.draw(
            draw, (x, y + h // 2), fit(row.text, text_font, right - x - aside_w - 24), colour, "lm"
        )
        if row.aside:
            aside_font.draw(
                draw,
                (right, y + h // 2),
                fit(row.aside, aside_font, aside_w),
                BLUE if card.big and row.strong else MUTED,
                "rm",
            )
        y += h
    return bottom
