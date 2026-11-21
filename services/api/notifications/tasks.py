from celery import shared_task

from . import push


@shared_task(name="notifications.drop_expired_push_devices", ignore_result=True)
def drop_expired_push_devices() -> int:
    """Drop push devices whose subscription ran out (TASK-034)."""
    return push.drop_expired()
