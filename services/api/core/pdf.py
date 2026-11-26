"""A plain text PDF, written by hand: A4 pages of fixed-width text in a built-in font. Enough for a
results sheet or a set of accounts, with no extra dependency.

The built-in fonts cover Latin-1; a character outside it is printed as "?".
"""

import io
import textwrap

WIDTH = 98  # characters across a page at 9 pt Courier with 40 pt margins
PER_PAGE = 54


def _escape(value: str) -> str:
    safe = value.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap(lines: list[str]) -> list[str]:
    """Lines no wider than the page; a long one continues on the next, keeping its indent."""
    out = []
    for line in lines:
        if len(line) <= WIDTH:
            out.append(line)
            continue
        indent = line[: len(line) - len(line.lstrip())]
        out += textwrap.wrap(line, WIDTH, subsequent_indent=indent + "  ", break_long_words=True) or [""]
    return out


def text_pdf(lines: list[str]) -> bytes:
    rows = wrap(lines)
    pages = [rows[i : i + PER_PAGE] for i in range(0, len(rows), PER_PAGE)] or [[]]
    font = 3 + 2 * len(pages)
    objects: list[bytes] = []
    kids = []
    for index, page in enumerate(pages):
        body = "BT /F1 9 Tf 40 800 Td 14 TL " + " ".join(f"({_escape(line)}) Tj T*" for line in page) + " ET"
        stream = body.encode("latin-1")
        page_id, content_id = 3 + 2 * index, 4 + 2 * index
        kids.append(f"{page_id} 0 R")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    head = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode(),
    ]
    tail = [b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate([*head, *objects, *tail], start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + obj + b"\nendobj\n")
    start = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(offsets) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(offsets) + 1, start))
    return out.getvalue()
