"""A small transactional outbox (REQ-015, the part of TASK-007 that official results need).

`enqueue` writes a job in the caller's transaction. `work` does due jobs one at a time: the handler's
own database writes and the job being marked done commit together, so a worker that dies part-way
leaves the job pending and nothing half-done, and the next run does it once. Handlers must still be
safe to run twice, because anything they do outside the database is not undone by a rollback.

Jobs are done by a worker process, never inside the request that wrote them (deployment.md): today
that is `manage.py work_outbox`, which polls for due jobs and retries what failed. Celery will call
the same `work` when it arrives (TASK-007).
"""

import logging
from collections.abc import Callable
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Job

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
HANDLERS: dict[str, Callable[[dict], None]] = {}


def handler(kind: str):
    """Register the function that does jobs of this kind. It gets the job's payload."""

    def register(function):
        HANDLERS[kind] = function
        return function

    return register


def enqueue(kind: str, key: str, payload: dict | None = None) -> Job:
    """Write the job with the change it follows from. The same key again is the same job."""
    job, _ = Job.objects.get_or_create(key=key, defaults={"kind": kind, "payload": payload or {}})
    return job


def work(limit: int = 100) -> int:
    """Do up to `limit` due jobs, oldest first. Returns how many were tried."""
    tried = 0
    while tried < limit:
        with transaction.atomic():
            job = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(status=Job.Status.PENDING, available_at__lte=timezone.now())
                .order_by("created_at", "id")
                .first()
            )
            if job is None:
                break
            _attempt(job)
        tried += 1
    return tried


def _attempt(job: Job) -> None:
    job.attempts += 1
    try:
        do = HANDLERS[job.kind]
        with transaction.atomic():  # what the handler wrote goes if it fails, the attempt count stays
            do(job.payload)
    except Exception as error:
        logger.exception("Outbox job %s (%s) failed, attempt %s", job.key, job.kind, job.attempts)
        job.last_error = f"{type(error).__name__}: {error}"[:500]
        if job.attempts >= MAX_ATTEMPTS:
            job.status = Job.Status.FAILED
        else:
            job.available_at = timezone.now() + timedelta(seconds=min(2**job.attempts, 300))
    else:
        job.status = Job.Status.DONE
        job.done_at = timezone.now()
        job.last_error = ""
    job.save(update_fields=["attempts", "status", "available_at", "last_error", "done_at"])
