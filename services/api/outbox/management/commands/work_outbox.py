import time

from django.core.management.base import BaseCommand

from outbox import service


class Command(BaseCommand):
    help = "Do the jobs written to the outbox. Runs until stopped; --once does what is due and exits."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--every", type=float, default=2.0, help="Seconds to wait when nothing is due.")

    def handle(self, *args, once: bool, every: float, **options):
        while True:
            tried = service.work()
            if once:
                self.stdout.write(f"{tried} job(s) tried")
                return
            if tried == 0:
                time.sleep(every)
