from django.core.management.base import BaseCommand
from django.db import transaction

from facilities.models import Visit
from finance import posting


class Command(BaseCommand):
    help = (
        "Post door visits recorded before the ledger took them (TASK-104), and reverse those since reversed. "
        "Safe to run again: each visit posts once."
    )

    def handle(self, *args, **options):
        posted = 0
        for visit in Visit.objects.filter(amount_minor__gt=0).select_related(
            "venue__organization", "pass_sold"
        ):
            with transaction.atomic():
                if posting.post_visit(visit) is not None:
                    posted += 1
                if visit.reversed_at:
                    posting.reverse_visit(visit, visit.reversed_by, visit.reversal_reason)
        self.stdout.write(f"{posted} paid visits in the ledger")
