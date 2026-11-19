from django.core.management.base import BaseCommand

from finance import dues
from organizations.committee import local_today
from organizations.models import Organization


class Command(BaseCommand):
    help = (
        "Generate every open contribution campaign's dues to date and send due and overdue reminders "
        "(REQ-023). Run it daily; running it again repeats nothing."
    )

    def handle(self, *args, **options):
        made = reminded = 0
        for organization in Organization.objects.filter(campaigns__isnull=False).distinct():
            made += dues.catch_up(organization)
            reminded += dues.remind(organization, local_today(organization))
        self.stdout.write(f"{made} dues generated, {reminded} reminders sent")
