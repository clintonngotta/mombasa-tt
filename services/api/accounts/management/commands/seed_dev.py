import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User

# Mirrors apps/web/src/lib/devAccounts.ts. Club roles arrive with organizations (TASK-012/013);
# until then these are plain verified users.
DEV_USERS = [
    ("player@mombasa-tt.test", "Test Player"),
    ("umpire@mombasa-tt.test", "Test Umpire"),
    ("admin@mombasa-tt.test", "Test Club Admin"),
]


class Command(BaseCommand):
    help = "Create or reset the verified development test accounts. Refuses to run unless DJANGO_DEBUG is on."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev only runs with DJANGO_DEBUG=true. Never seed test logins in production."
            )

        password = os.environ.get("DEV_LOGIN_PASSWORD", "mombasa-tt-dev")
        for email, display_name in DEV_USERS:
            user, created = User.objects.get_or_create(email=email, defaults={"display_name": display_name})
            user.display_name = display_name
            user.email_verified_at = user.email_verified_at or timezone.now()
            user.is_active = True
            user.set_password(password)
            user.save()
            self.stdout.write(f"{'created' if created else 'reset'}  {email}")
