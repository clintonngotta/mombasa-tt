"""Sending alerts (REQ-019). Call `notify` inside the transaction that made the change."""

from collections.abc import Iterable

from django.db import IntegrityError, transaction

from . import push
from .models import ALWAYS_ON, Notification, Preference


def notify(
    recipients: Iterable,
    category: str,
    title: str,
    *,
    subject: str,
    version="1",
    body: str = "",
    link: str = "",
    organization=None,
) -> int:
    """One alert per recipient for this version of the subject; sending it again changes nothing. Older
    alerts of the same category about the subject are marked superseded. Recipients who switched the
    category off get nothing (except categories that can't be switched off). Returns how many were new."""
    ids = {getattr(r, "pk", r) for r in recipients if r is not None}
    if not ids:
        return 0
    if category not in ALWAYS_ON:
        ids -= set(
            Preference.objects.filter(user_id__in=ids, category=category).values_list("user_id", flat=True)
        )
    version = str(version)
    made = 0
    for user_id in ids:
        try:
            with transaction.atomic():
                alert = Notification.objects.create(
                    recipient_id=user_id,
                    category=category,
                    title=title[:140],
                    body=body[:500],
                    link=link,
                    subject=subject,
                    version=version,
                    organization=organization,
                )
                push.queue(alert)
            made += 1
        except IntegrityError:
            continue  # this version was already sent to them
        Notification.objects.filter(recipient_id=user_id, category=category, subject=subject).exclude(
            version=version
        ).update(superseded=True)
    return made


def supersede(subject: str, category: str | None = None) -> None:
    """The subject is gone or changed beyond its alerts (cancelled, recalled): mark them superseded."""
    alerts = Notification.objects.filter(subject=subject, superseded=False)
    if category:
        alerts = alerts.filter(category=category)
    alerts.update(superseded=True)
