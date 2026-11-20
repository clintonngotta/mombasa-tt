"""The Celery app (TASK-007). Redis is the broker; the outbox stays the source of truth.

Jobs are written to the outbox table with the change they follow from. Celery only says when to look:
a job written by a request wakes a worker as soon as its transaction commits, and beat sweeps every few
seconds for jobs whose retry is due or whose wake-up was lost. A worker killed part-way leaves its job
pending in the database, so a restart does it again, once.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mombasa_tt")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
