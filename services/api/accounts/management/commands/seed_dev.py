import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from core.models import Region
from facilities.models import Table, Venue
from organizations.models import Membership, OfficialAppointment, Organization, Role, seed_roles
from organizations.permissions import Permission, RoleKey
from profiles.models import profile_for

# Mirrors apps/web/src/lib/devAccounts.ts. Each user's place: (organization, role key or custom role name),
# or None for someone with no membership (the regional officer acts through an appointment instead).
DEV_CLUB = "Mombasa Dev TT Club"
DEV_FACILITY = "Coast Dev TT Centre"
DEV_REGION = ("KE", "Mombasa")
COACH_ROLE = "Coach"

DEV_USERS = [
    ("player@mombasa-tt.test", "Test Player", (DEV_CLUB, None)),
    ("umpire@mombasa-tt.test", "Test Umpire", (DEV_CLUB, RoleKey.ASSISTANT_CAPTAIN)),
    ("admin@mombasa-tt.test", "Test Club Admin", (DEV_CLUB, RoleKey.ADMIN)),
    ("coach@mombasa-tt.test", "Test Coach", (DEV_CLUB, COACH_ROLE)),
    ("facility@mombasa-tt.test", "Test Facility Manager", (DEV_FACILITY, RoleKey.ADMIN)),
    ("regional@mombasa-tt.test", "Test Regional Officer", None),
]
REGIONAL_OFFICER = "regional@mombasa-tt.test"


def _organization(name: str, kind: str) -> Organization:
    country, region = DEV_REGION
    organization = Organization.objects.filter(name=name).first()
    if organization is None:
        organization = Organization.objects.create(name=name, town="Mombasa", kind=kind)
        seed_roles(organization)
    # Inside the dev region, so the regional officer oversees it.
    if (organization.country, organization.region) != (country, region):
        organization.country, organization.region = country, region
        organization.save(update_fields=["country", "region"])
    return organization


def _facility() -> Organization:
    facility = _organization(DEV_FACILITY, Organization.Kind.FACILITY)
    venue = Venue.objects.filter(organization=facility, active=True).first()
    if venue is None:
        venue = Venue.objects.create(
            organization=facility, name="Nyali branch", town="Mombasa", address="Links Road, Nyali"
        )
    for n in range(1, 5):
        Table.objects.get_or_create(venue=venue, label=f"Table {n}", active=True, defaults={"position": n})
    return facility


def _coach_role(club: Organization) -> Role:
    role, _ = Role.objects.get_or_create(
        organization=club, key="", name=COACH_ROLE, defaults={"permissions": [Permission.TRAINING_MANAGE]}
    )
    return role


def _region() -> Region:
    country, name = DEV_REGION
    region = Region.objects.filter(country_id=country, name=name).first()
    if region is None:
        call_command("seed_geography", stdout=None)
        region = Region.objects.get(country_id=country, name=name)
    return region


class Command(BaseCommand):
    help = "Create or reset the verified development test accounts. Refuses to run unless DJANGO_DEBUG is on."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev only runs with DJANGO_DEBUG=true. Never seed test logins in production."
            )

        password = os.environ.get("DEV_LOGIN_PASSWORD", "mombasa-tt-dev")
        region = _region()
        organizations = {
            DEV_CLUB: _organization(DEV_CLUB, Organization.Kind.CLUB_FACILITY),
            DEV_FACILITY: _facility(),
        }
        for email, display_name, place in DEV_USERS:
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

            if place is None:
                OfficialAppointment.objects.get_or_create(user=user, country=region.country, region=region)
                where = f"regional official for {region}"
            else:
                org_name, role = place
                organization = organizations[org_name]
                membership, _ = Membership.objects.update_or_create(
                    organization=organization, user=user, defaults={"status": Membership.Status.ACTIVE}
                )
                if role == COACH_ROLE:
                    roles = [_coach_role(organization)]
                elif role:
                    roles = [organization.roles.get(key=role)]
                else:
                    roles = []
                membership.roles.set(roles)
                where = f"{role or 'member'} in {org_name}"
            self.stdout.write(f"{'created' if created else 'reset'}  {email} ({where})")
