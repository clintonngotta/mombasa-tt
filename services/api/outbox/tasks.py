from celery import shared_task

from . import service


@shared_task(name="outbox.work", ignore_result=True)
def work() -> int:
    """Do the due outbox jobs. Safe to run in several workers at once: each job is taken under a row lock
    that other workers skip."""
    return service.work()
