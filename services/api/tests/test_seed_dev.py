"""The development test logins (seed_dev): one per kind of user the login screen offers."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User
from coaching.models import CoachProfile
from facilities.models import Table
from organizations.access import effective_permissions, managed_organizations
from organizations.models import Membership, OfficialAppointment, Organization
from organizations.permissions import Permission


def seed():
    call_command("seed_dev", stdout=None)


def test_seed_dev_refuses_without_debug(db, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        seed()


def test_seed_dev_creates_every_test_login_and_runs_again_cleanly(db, settings):
    settings.DEBUG = True
    seed()
    seed()

    emails = {"player", "umpire", "admin", "coach", "facility", "regional"}
    users = User.objects.filter(email__in=[f"{e}@mombasa-tt.test" for e in emails])
    assert users.count() == len(emails)
    assert all(u.email_verified_at and u.check_password("mombasa-tt-dev") for u in users)

    club = Organization.objects.get(name="Mombasa Dev TT Club")
    coach = User.objects.get(email="coach@mombasa-tt.test")
    assert Permission.TRAINING_MANAGE in effective_permissions(coach, club)
    assert Permission.MEMBERS_MANAGE not in effective_permissions(coach, club)
    assert CoachProfile.objects.filter(user=coach, organizations=club).count() == 1

    facility = Organization.objects.get(name="Coast Dev TT Centre")
    assert facility.kind == Organization.Kind.FACILITY
    manager = Membership.objects.get(organization=facility, user__email="facility@mombasa-tt.test")
    assert manager.roles.filter(key="admin").exists()
    assert Table.objects.filter(venue__organization=facility, active=True).count() == 4

    officer = User.objects.get(email="regional@mombasa-tt.test")
    assert OfficialAppointment.objects.filter(user=officer, region__name="Mombasa").count() == 1
    assert not Membership.objects.filter(user=officer).exists()
    assert set(managed_organizations(officer)) >= {club, facility}
