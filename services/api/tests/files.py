"""Reading back the files the API makes: the text of a PDF, the size of a PNG."""

import io
import struct

from pypdf import PdfReader

PNG = b"\x89PNG\r\n\x1a\n"


def pdf_pages(content: bytes) -> list[str]:
    assert content.startswith(b"%PDF-") and content.rstrip().endswith(b"%%EOF")
    return [page.extract_text() for page in PdfReader(io.BytesIO(content)).pages]


def pdf_text(content: bytes) -> str:
    return "\n".join(pdf_pages(content))


def png_size(content: bytes) -> tuple[int, int]:
    assert content.startswith(PNG)
    return struct.unpack(">II", content[16:24])
