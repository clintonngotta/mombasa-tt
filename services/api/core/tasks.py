from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone


@shared_task(name="core.forget_idempotency_keys", ignore_result=True)
def forget_idempotency_keys() -> int:
    """Forget changes sent with an Idempotency-Key once no app could still be retrying them."""
    from .models import IdempotentRequest

    cutoff = timezone.now() - timedelta(days=settings.IDEMPOTENCY_KEEP_DAYS)
    deleted, _ = IdempotentRequest.objects.filter(created_at__lt=cutoff).delete()
    return deleted
