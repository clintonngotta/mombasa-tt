"""Signed, short-lived links to attachment content (REQ-020).

A link is issued only after the access check passes (attachments.access.can_read), and it carries its own
proof: the content endpoint needs no session, only an unexpired signature for that attachment. Losing
access stops new links; a link already issued works until it expires (ATTACHMENT_URL_TTL seconds).
"""

from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

SALT = "attachments.content"


def link(attachment_id) -> dict:
    """{id, url, expires_at} for an attachment the caller has already been allowed to read."""
    token = signing.dumps(str(attachment_id), salt=SALT)
    path = reverse("attachment-content", kwargs={"pk": attachment_id})
    return {
        "id": attachment_id,
        "url": f"{path}?token={token}",
        "expires_at": timezone.now() + timedelta(seconds=settings.ATTACHMENT_URL_TTL),
    }


def token_is_valid(token: str, attachment_id) -> bool:
    try:
        signed_id = signing.loads(token, salt=SALT, max_age=settings.ATTACHMENT_URL_TTL)
    except signing.BadSignature:  # includes SignatureExpired
        return False
    return signed_id == str(attachment_id)
