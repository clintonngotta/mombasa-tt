from django.core.management.base import BaseCommand
from django.db import transaction

from ratings import service
from ratings.models import Discipline


class Command(BaseCommand):
    help = "Write the rating ledgers again from nothing, out of the official results that stand."

    def handle(self, *args, **options):
        for discipline in Discipline.values:
            with transaction.atomic():
                written = service.rebuild(discipline)
            self.stdout.write(f"{discipline}: {written} rating event(s)")
