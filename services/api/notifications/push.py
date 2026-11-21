"""Browser push for inbox alerts (REQ-019, TASK-034).

Push is a best-effort copy of the inbox, never the record. When an alert is written, one outbox job per
device of the recipient is written with it (the job's key names the alert and the device, so the same
alert never goes to a device twice). The worker sends it later and, before sending, looks again: an alert
that was read or superseded meanwhile is not sent, so a stale "Called to table" never arrives after the
call changed. A device the push service says is gone (404, 410) is dropped; a busy or unreachable push
service is retried with the outbox's back-off, and every message carries a time to live so a late one
is discarded by the push service rather than shown hours later.
"""

import hashlib
import logging
from fnmatch import fnmatch
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

from outbox import service as outbox

from . import webpush
from .models import ALWAYS_ON, Notification, PushSubscription

logger = logging.getLogger(__name__)

SEND = "notifications.push"
# Refusals in a row (other than "gone") before a device is dropped.
MAX_FAILURES = 3
# How long a push service keeps trying to deliver: a table call is useless after a few minutes, other
# alerts after a day. The inbox still has them.
TTL_SECONDS = {"table_call": 10 * 60, "up_next": 15 * 60, "assignment": 60 * 60}
DEFAULT_TTL = 24 * 60 * 60


class Busy(Exception):
    """The push service didn't take the message this time; the outbox tries again later."""


def configured() -> bool:
    return bool(settings.WEB_PUSH_PRIVATE_KEY)


def public_key() -> str:
    return webpush.public_key_for(settings.WEB_PUSH_PRIVATE_KEY) if configured() else ""


def allowed_endpoint(endpoint: str) -> bool:
    """Only https addresses on the browsers' push services (settings.WEB_PUSH_HOSTS)."""
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443):
        return False
    host = parts.hostname.lower()
    return any(fnmatch(host, pattern.lower()) for pattern in settings.WEB_PUSH_HOSTS)


def queue(alert: Notification) -> None:
    """Write the push jobs for a new alert, in the transaction that wrote it."""
    if not configured():
        return
    devices = PushSubscription.objects.filter(user_id=alert.recipient_id).values_list("id", flat=True)
    for device in devices:
        outbox.enqueue(SEND, f"push:{alert.id}:{device}", {"alert": str(alert.id), "device": str(device)})


def message(alert: Notification) -> dict:
    """What the service worker shows. `tag` is the subject, so a newer alert about the same thing
    replaces the older one on the device instead of piling up."""
    return {
        "id": str(alert.id),
        "title": alert.title,
        "body": alert.body,
        "link": alert.link or "/notifications",
        "tag": alert.subject,
        "category": alert.category,
        "urgent": alert.category in ALWAYS_ON,
    }


def _topic(subject: str) -> str:
    """RFC 8030 topic: at most 32 base64url characters. An undelivered message with the same topic is
    replaced by the newer one."""
    return webpush.b64url_encode(hashlib.sha256(subject.encode()).digest())[:32]


@outbox.handler(SEND)
def send(payload: dict) -> None:
    alert = Notification.objects.filter(pk=payload["alert"]).first()
    device = PushSubscription.objects.filter(pk=payload["device"]).first()
    if alert is None or device is None or device.user_id != alert.recipient_id:
        return  # the device was removed or changed hands since
    if alert.superseded or alert.read_at is not None or not configured():
        return  # stale: the inbox already shows where things stand
    if device.expires_at and device.expires_at <= timezone.now():
        device.delete()
        return
    result = webpush.send(
        device.endpoint,
        device.p256dh,
        device.auth,
        message(alert),
        private_key_b64=settings.WEB_PUSH_PRIVATE_KEY,
        subject=settings.WEB_PUSH_SUBJECT,
        ttl=TTL_SECONDS.get(alert.category, DEFAULT_TTL),
        topic=_topic(alert.subject),
    )
    if result.delivered:
        device.last_sent_at = timezone.now()
        device.failures = 0
        device.save(update_fields=["last_sent_at", "failures"])
    elif result.gone:
        device.delete()
    elif result.status == 429 or result.status >= 500 or result.status == 0:
        raise Busy(f"push service answered {result.status or 'nothing'}")
    else:
        # Refused (400, 401, 403, 413): retrying the same message won't help. A device that keeps
        # refusing (a key that no longer matches, say) is dropped.
        logger.warning("Push to device %s refused with %s", device.pk, result.status)
        device.failures += 1
        if device.failures >= MAX_FAILURES:
            device.delete()
        else:
            device.save(update_fields=["failures"])


def drop_expired() -> int:
    """Drop devices whose subscription ran out (the browser said when). Devices a push service says are
    gone are dropped when a message to them is refused."""
    count, _ = PushSubscription.objects.filter(expires_at__lte=timezone.now()).delete()
    return count
