import logging
import time

from django.core.management.base import BaseCommand
from django.db import Error, close_old_connections

from outbox import service

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Do the jobs written to the outbox. Runs until stopped; --once does what is due and exits."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--every", type=float, default=2.0, help="Seconds to wait when nothing is due.")

    def handle(self, *args, once: bool, every: float, **options):
        while True:
            close_old_connections()  # a connection the database dropped is replaced, not reused
            try:
                tried = service.work()
            except Error:
                if once:
                    raise
                # The database went away for a moment: the jobs are still written there. Try again.
                logger.exception("The outbox worker could not reach the database")
                close_old_connections()
                time.sleep(every)
                continue
            if once:
                self.stdout.write(f"{tried} job(s) tried")
                return
            if tried == 0:
                time.sleep(every)
