"""Branded PDFs: A4 pages in the Coast Loopas look (core/brand.py), with the logo at the head of the first
page, a faint logo behind every page, and the content as tables and cards.

The pages look like the share images: the logo and title on navy at the head of the first page, white
cards and tables on a light page, a navy foot with the site. A document is a title, a subtitle and a list
of blocks: Heading, Table, Card, Text and the share image's own cards (brand.Card: rows with a score or a
club on the right, medals for places). Every piece of text is escaped before it reaches the layout engine,
so names and posts can't inject markup.
"""

import io
from dataclasses import dataclass, field
from functools import cache
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFNameBytes, TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from reportlab.platypus import Table as Grid

from . import brand

REGULAR, SEMI, BOLD = "Barlow", "Barlow-SemiBold", "Barlow-Bold"
MARGIN = 16 * mm
PAGE_W, PAGE_H = A4
FRAME_W = PAGE_W - 2 * MARGIN
MAX_ROWS = 2000  # a table longer than this is cut, saying so
KEEP_WHOLE = 12  # a table up to this many rows stays on one page with its title


WEIGHTS = {REGULAR: 400, SEMI: 600, BOLD: 700}


@cache
def _fonts() -> None:
    for name, weight in WEIGHTS.items():
        pdfmetrics.registerFont(TTFont(name, str(brand.font_path(weight))))
        extended = TTFont(f"{name}-ext", str(brand.font_path(weight, extended=True)))
        # Both files carry one internal name; the PDF would take them for one font and drop the letters.
        extended.face.name = TTFNameBytes(extended.face.name + b"-Ext")
        pdfmetrics.registerFont(extended)
    pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD, italic=REGULAR, boldItalic=BOLD)


def _c(hex_colour: str):
    return colors.HexColor(hex_colour)


@cache
def _faded_logo() -> ImageReader:
    """The logo at a few percent opacity, for behind the page."""
    image = Image.open(brand.LOGO).convert("RGBA")
    image.putalpha(image.getchannel("A").point(lambda a: a * 0.06))
    out = io.BytesIO()
    image.save(out, format="PNG")
    out.seek(0)
    return ImageReader(out)


def _style(
    name: str, font: str = REGULAR, size: float = 11, colour: str = brand.INK, **more
) -> ParagraphStyle:
    return ParagraphStyle(
        name, fontName=font, fontSize=size, leading=size * 1.25, textColor=_c(colour), **more
    )


TITLE = _style("title", BOLD, 24, brand.WHITE)
SUBTITLE = _style("subtitle", SEMI, 13, brand.GOLD)
ROW = _style("row", SEMI, 12)
ROW_STRONG = _style("row-strong", BOLD, 12, brand.BLUE)
ROW_NOTE = _style("row-note", SEMI, 9.5, brand.MUTED)
ASIDE = _style("aside", SEMI, 10, brand.MUTED, alignment=TA_RIGHT)
HEADING = _style("heading", BOLD, 15, brand.NAVY)
CELL = _style("cell", REGULAR, 11)
CELL_STRONG = _style("cell-strong", SEMI, 11)
CELL_RIGHT = _style("cell-right", REGULAR, 11, alignment=TA_RIGHT)
HEAD = _style("head", BOLD, 10.5, brand.WHITE)
HEAD_RIGHT = _style("head-right", BOLD, 10.5, brand.WHITE, alignment=TA_RIGHT)
RANK = _style("rank", BOLD, 12, brand.NAVY, alignment=TA_CENTER)
CARD_TITLE = _style("card-title", BOLD, 14, brand.BLUE)
META = _style("meta", SEMI, 10, brand.MUTED)
BODY = _style("body", REGULAR, 11)
NOTE = _style("note", REGULAR, 10, brand.MUTED)


@dataclass
class Heading:
    text: str


@dataclass
class Text:
    text: str
    muted: bool = False


@dataclass
class Table:
    """Rows under a blue header row. `widths` are shares of the page width; `right` lists the columns
    aligned right (amounts); with `ranked`, the first column is a place and 1 to 3 get medal colours.
    In a table that isn't ranked, a row whose cells after the first are all empty is a section row."""

    columns: list[str]
    rows: list[list[str]]
    widths: list[float] | None = None
    right: tuple[int, ...] = ()
    ranked: bool = False
    title: str = ""
    empty: str = "Nothing to show."


@dataclass
class Card:
    """A boxed item: a title, a line of details, then its text, line by line."""

    title: str
    meta: str = ""
    lines: list[str] = field(default_factory=list)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    """Text as a paragraph: escaped, and letters the main font lacks set in the extended one."""
    marked = "".join(
        f'<font name="{style.fontName}-ext">{escape(part)}</font>' if ext else escape(part)
        for part, ext in brand.runs(text or "")
    )
    return Paragraph(marked.replace("\n", "<br/>"), style)


def _heading(text: str):
    bar = Grid([[_p(text.upper(), HEADING)]], colWidths=[FRAME_W])
    bar.setStyle(
        TableStyle(
            [
                ("LINEBEFORE", (0, 0), (0, 0), 4, _c(brand.GOLD)),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return bar


def _grid(block: Table):
    rows = block.rows[:MAX_ROWS]
    count = len(block.columns)
    widths = block.widths or [1] * count
    col_widths = [FRAME_W * w / sum(widths) for w in widths]
    data = [[_p(c.upper(), HEAD_RIGHT if i in block.right else HEAD) for i, c in enumerate(block.columns)]]
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), _c(brand.WHITE)),
        ("BACKGROUND", (0, 0), (-1, 0), _c(brand.BLUE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, _c(brand.LINE)),
        ("BOX", (0, 0), (-1, -1), 0.8, _c(brand.LINE)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]
    for number, row in enumerate(rows, start=1):
        cells = ([str(cell) for cell in row] + [""] * count)[:count]
        if count > 1 and not block.ranked and not any(cells[1:]):
            data.append([_p(cells[0], CELL_STRONG)] + [""] * (count - 1))
            style += [
                ("SPAN", (0, number), (-1, number)),
                ("BACKGROUND", (0, number), (-1, number), _c(brand.SKY)),
            ]
            continue
        data.append(
            [
                _p(cell, RANK if block.ranked and i == 0 else CELL_RIGHT if i in block.right else CELL)
                for i, cell in enumerate(cells)
            ]
        )
        place = int(cells[0]) if block.ranked and cells[0].isdigit() else 0
        if place in brand.MEDAL:
            style.append(("BACKGROUND", (0, number), (0, number), _c(brand.MEDAL[place])))
        elif not block.ranked and number % 2 == 0:
            style.append(("BACKGROUND", (0, number), (-1, number), _c("#f7fafd")))
    grid = Grid(data, colWidths=col_widths, repeatRows=1)
    grid.setStyle(TableStyle(style))
    return grid


def _table(block: Table) -> list:
    head = [_heading(block.title), Spacer(1, 3 * mm)] if block.title else []
    if not block.rows:
        return [KeepTogether([*head, _p(block.empty, NOTE)])]
    body = [_grid(block)]
    if len(block.rows) > MAX_ROWS:
        body.append(_p(f"…and {len(block.rows) - MAX_ROWS} more rows.", NOTE))
    if len(block.rows) <= KEEP_WHOLE:
        return [KeepTogether([*head, *body])]
    return [*head, *body]


def _card(block: Card):
    data = [[_p(block.title, CARD_TITLE)]]
    if block.meta:
        data.append([_p(block.meta, META)])
    for line in block.lines:
        data.append([_p(line, BODY) if line.strip() else Spacer(1, 2 * mm)])
    grid = Grid(data, colWidths=[FRAME_W])
    grid.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _c(brand.WHITE)),
                ("BOX", (0, 0), (-1, -1), 0.8, _c(brand.LINE)),
                ("LINEBEFORE", (0, 0), (0, -1), 4, _c(brand.GOLD)),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ]
        )
    )
    return grid


class _Badge(Flowable):
    """A place in a circle: gold, silver and bronze for 1 to 3."""

    SIZE = 6.6 * mm

    def __init__(self, badge: int | str):
        super().__init__()
        self.badge = badge
        self.width = self.height = self.SIZE

    def draw(self):
        medal = brand.MEDAL.get(self.badge) if isinstance(self.badge, int) else None
        r = self.SIZE / 2
        self.canv.setFillColor(_c(medal or brand.SKY))
        self.canv.setStrokeColor(_c(brand.NAVY if medal else brand.LINE))
        self.canv.setLineWidth(0.8)
        self.canv.circle(r, r, r - 0.4, stroke=1, fill=1)
        self.canv.setFillColor(_c(brand.NAVY))
        self.canv.setFont(BOLD, 10)
        self.canv.drawCentredString(r, r - 3.4, str(self.badge)[:3])


def _sheet(card: brand.Card):
    """A share image's card on paper: the title in blue capitals beside a gold tab, then its rows, with a
    line between two rows that follow each other. It runs over pages, repeating its title."""
    side, badge, aside = 5 * mm, 9 * mm, FRAME_W * 0.32
    widths = [side, badge, FRAME_W - 2 * side - badge - aside, aside, side]
    data: list[list] = [["", _p(card.title.upper(), CARD_TITLE), "", "", ""]]
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), _c(brand.WHITE)),
        ("BOX", (0, 0), (-1, -1), 0.8, _c(brand.LINE)),
        ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("SPAN", (1, 0), (3, 0)),
        ("LINEBEFORE", (0, 0), (0, 0), 6, _c(brand.GOLD)),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ]
    for number, row in enumerate(card.rows, start=1):
        if row.note:
            data.append(["", _p(row.text, ROW_NOTE), "", "", ""])
            style += [
                ("SPAN", (1, number), (3, number)),
                ("TOPPADDING", (0, number), (-1, number), 4),
                ("BOTTOMPADDING", (0, number), (-1, number), 1),
            ]
            if number < len(card.rows):  # a round's name stays with the match under it
                style.append(("NOSPLIT", (0, number), (-1, number + 1)))
            continue
        text = _p(row.text, ROW_STRONG if row.strong else ROW)
        if row.badge is None:
            data.append(["", text, "", _p(row.aside, ASIDE), ""])
            style.append(("SPAN", (1, number), (2, number)))
        else:
            data.append(["", _Badge(row.badge), text, _p(row.aside, ASIDE), ""])
        if number > 1 and not card.rows[number - 2].note:
            style.append(("LINEABOVE", (1, number), (3, number), 0.6, _c(brand.LINE)))
    style.append(("BOTTOMPADDING", (0, len(data) - 1), (-1, len(data) - 1), 9))
    grid = Grid(data, colWidths=widths, repeatRows=1)
    grid.setStyle(TableStyle(style))
    return grid


class _Header(Flowable):
    """The head of the first page, as on the share images: the logo, the title in capitals and the subtitle
    on navy across the whole page, over a cyan line."""

    LOGO_H = 26 * mm

    def __init__(self, title: str, subtitle: str):
        super().__init__()
        self.parts = [_p(title.upper(), TITLE), *([_p(subtitle, SUBTITLE)] if subtitle else [])]

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        self.heights = [part.wrap(avail_width, avail_height)[1] for part in self.parts]
        self.height = self.LOGO_H + 4 * mm + sum(self.heights) + 2 * len(self.heights) + 7 * mm
        return self.width, self.height

    def draw(self):
        canv = self.canv
        x, y = canv.absolutePosition(0, 0)
        canv.setFillColor(_c(brand.NAVY))
        canv.rect(-x, 0, PAGE_W, PAGE_H - y, stroke=0, fill=1)
        canv.setFillColor(_c(brand.CYAN))
        canv.rect(-x, 0, PAGE_W, 1.6 * mm, stroke=0, fill=1)
        top = self.height
        canv.drawImage(
            str(brand.LOGO_REVERSED),
            0,
            top - self.LOGO_H,
            self.LOGO_H * 720 / 444,
            self.LOGO_H,
            mask="auto",
        )
        top -= self.LOGO_H + 4 * mm
        for part, height in zip(self.parts, self.heights, strict=True):
            part.drawOn(canv, 0, top - height)
            top -= height + 2


FOOT = 12 * mm


def _page(prepared_by: str, title: str):
    """What lies under a page's content: the light page with the faint logo, the navy bar at the top and
    the navy foot."""

    def paint(canv, doc) -> None:
        canv.saveState()
        canv.setFillColor(_c(brand.SKY))
        canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        w = PAGE_W * 0.7
        h = w * 444 / 720
        canv.drawImage(_faded_logo(), (PAGE_W - w) / 2, (PAGE_H - h) / 2 - 10 * mm, w, h, mask="auto")
        canv.setFillColor(_c(brand.NAVY))
        canv.rect(0, PAGE_H - 5 * mm, PAGE_W, 5 * mm, stroke=0, fill=1)
        canv.rect(0, 0, PAGE_W, FOOT, stroke=0, fill=1)
        canv.setFillColor(_c(brand.GOLD))
        canv.rect(0, PAGE_H - 6.2 * mm, PAGE_W, 1.2 * mm, stroke=0, fill=1)
        canv.rect(0, FOOT, PAGE_W, 1.2 * mm, stroke=0, fill=1)
        canv.setFillColor(_c(brand.WHITE))
        canv.setFont(BOLD, 12)
        canv.drawString(MARGIN, 4.4 * mm, brand.SITE)
        canv.setFillColor(_c(brand.CYAN))
        canv.setFont(SEMI, 11)
        canv.drawRightString(PAGE_W - MARGIN, 4.4 * mm, "COAST TABLE TENNIS")
        canv.setFillColor(_c(brand.MUTED))
        canv.setFont(SEMI, 9)
        if doc.page > 1:
            canv.drawString(MARGIN, PAGE_H - 11 * mm, title[:110])
        if prepared_by:
            canv.drawString(MARGIN, FOOT + 4 * mm, f"Prepared by: {prepared_by}"[:90])
        canv.restoreState()

    return paint


def _canvas_maker():
    class Numbered(pdf_canvas.Canvas):
        """Adds "page 2 of 3" to each page, once the page count is known."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._frame(total)
                super().showPage()
            super().save()

        def _frame(self, total: int) -> None:
            self.setFont(SEMI, 9)
            self.setFillColor(_c(brand.MUTED))
            self.drawRightString(PAGE_W - MARGIN, FOOT + 4 * mm, f"Page {self._pageNumber} of {total}")

    return Numbered


def document(title: str, subtitle: str, blocks: list, prepared_by: str = "") -> bytes:
    """The PDF: the logo, the title and subtitle, then the blocks in order."""
    _fonts()
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=14 * mm,
        bottomMargin=FOOT + 9 * mm,
        title=title,
        author=prepared_by or "Coast Table Tennis",
        creator=brand.SITE,
    )
    story: list = [_Header(title, subtitle), Spacer(1, 7 * mm)]
    for block in blocks:
        if isinstance(block, Heading):
            story += [_heading(block.text), Spacer(1, 3 * mm)]
        elif isinstance(block, Table):
            story += [*_table(block), Spacer(1, 7 * mm)]
        elif isinstance(block, Card):
            story += [_card(block), Spacer(1, 5 * mm)]
        elif isinstance(block, brand.Card):
            story += [_sheet(block), Spacer(1, 5 * mm)]
        elif isinstance(block, Text):
            story += [_p(block.text, NOTE if block.muted else BODY), Spacer(1, 3 * mm)]
    paint = _page(prepared_by, title)
    doc.build(story, onFirstPage=paint, onLaterPages=paint, canvasmaker=_canvas_maker())
    return out.getvalue()
