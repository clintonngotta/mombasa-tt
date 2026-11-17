import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from organizations.models import Membership, Organization, seed_roles
from organizations.permissions import RoleKey
from profiles.models import profile_for

# Mirrors apps/web/src/lib/devAccounts.ts. The last item is the role each holds in the dev club
# (None = plain member).
DEV_USERS = [
    ("player@mombasa-tt.test", "Test Player", None),
    ("umpire@mombasa-tt.test", "Test Umpire", RoleKey.ASSISTANT_CAPTAIN),
    ("admin@mombasa-tt.test", "Test Club Admin", RoleKey.ADMIN),
]
DEV_CLUB = "Mombasa Dev TT Club"


class Command(BaseCommand):
    help = "Create or reset the verified development test accounts. Refuses to run unless DJANGO_DEBUG is on."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev only runs with DJANGO_DEBUG=true. Never seed test logins in production."
            )

        password = os.environ.get("DEV_LOGIN_PASSWORD", "mombasa-tt-dev")
        club = Organization.objects.filter(name=DEV_CLUB).first()
        if club is None:
            club = Organization.objects.create(
                name=DEV_CLUB, town="Mombasa", kind=Organization.Kind.CLUB_FACILITY
            )
            seed_roles(club)
        for email, display_name, role_key in DEV_USERS:
            user, created = User.objects.get_or_create(email=email, defaults={"display_name": display_name})
            user.display_name = display_name
            user.email_verified_at = user.email_verified_at or timezone.now()
            user.is_active = True
            user.set_password(password)
            user.save()
            # Test logins skip onboarding, so logging in goes straight to the app.
            profile = profile_for(user)
            if profile.onboarding_completed_at is None:
                profile.onboarding_completed_at = timezone.now()
                profile.save(update_fields=["onboarding_completed_at", "updated_at"])
            membership, _ = Membership.objects.update_or_create(
                organization=club, user=user, defaults={"status": Membership.Status.ACTIVE}
            )
            membership.roles.set([club.roles.get(key=role_key)] if role_key else [])
            self.stdout.write(
                f"{'created' if created else 'reset'}  {email} ({role_key or 'member'} in {DEV_CLUB})"
            )
