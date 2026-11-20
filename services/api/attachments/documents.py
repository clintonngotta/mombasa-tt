"""Validate uploaded documents (REQ-007): PDFs only, checked by their content rather than their name."""

from rest_framework.exceptions import ValidationError

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
PDF_CONTENT_TYPE = "application/pdf"
NOT_A_PDF = "Choose a PDF document."


def read_pdf(upload) -> bytes:
    """The bytes of `upload` if it is a PDF under the size limit. Raises ValidationError with a message for
    the person uploading."""
    if upload.size > MAX_DOCUMENT_BYTES:
        raise ValidationError({"file": "Choose a PDF under 10 MB."})
    content = upload.read()
    # A PDF starts with its header within the first kilobyte (most readers allow leading junk there).
    if b"%PDF-" not in content[:1024]:
        raise ValidationError({"file": NOT_A_PDF})
    return content
