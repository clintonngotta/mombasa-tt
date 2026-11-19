from django.core.management.base import BaseCommand

from finance import dues
from organizations.models import Organization


class Command(BaseCommand):
    help = (
        "Generate every open contribution campaign's dues to date (REQ-023). Safe to run any number of times."
    )

    def handle(self, *args, **options):
        made = sum(
            dues.catch_up(org)
            for org in Organization.objects.filter(campaigns__closed_at__isnull=True).distinct()
        )
        self.stdout.write(f"{made} dues generated")
