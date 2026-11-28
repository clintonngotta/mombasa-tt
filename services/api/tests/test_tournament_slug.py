"""A tournament's public link names it by slug (/tournaments/<slug>), not by its id."""

from importlib import import_module

import pytest
from django.apps import apps

from competitions.models import Tournament

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_tournaments import TOURNAMENTS, add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
BY_SLUG = TOURNAMENTS + "by-slug/"


def test_slug_comes_from_the_name_and_year_and_stays_unique(staff, club):
    first = make_tournament(staff, club, name="Coast Open!")
    second = make_tournament(staff, club, name="Coast Open")
    third = make_tournament(staff, club, name="Coast Open 2026")
    assert first["slug"] == "coast-open-2026"
    assert second["slug"] == "coast-open-2026-2"
    # A name that already carries the year doesn't get it twice.
    assert third["slug"] == "coast-open-2026-3"


def test_slug_survives_a_rename_and_cannot_be_set(staff, club):
    tournament = make_tournament(staff, club)
    renamed = staff.patch(url(tournament), {"name": "Coast Masters", "slug": "mine"}, format="json")
    assert renamed.status_code == 200, renamed.json()
    assert renamed.json()["name"] == "Coast Masters"
    assert renamed.json()["slug"] == "coast-open-2026"


def test_a_published_tournament_is_found_by_slug_signed_out(staff, club):
    tournament = add_event(staff, make_tournament(staff, club, make_venue(staff, club)))
    do(staff, tournament, "publish")
    found = BrowserClient().get(f"{BY_SLUG}{tournament['slug']}/")
    assert found.status_code == 200
    assert found.json()["id"] == tournament["id"]
    assert found.json() == BrowserClient().get(url(tournament)).json()


def test_a_draft_is_found_by_slug_only_by_its_staff(staff, club):
    draft = make_tournament(staff, club)
    link = f"{BY_SLUG}{draft['slug']}/"
    assert staff.get(link).status_code == 200
    assert BrowserClient().get(link).status_code == 404
    assert logged_in(make_user("stranger@example.com")).get(link).status_code == 404


def test_an_unknown_or_overlong_slug_is_not_found(staff):
    assert staff.get(f"{BY_SLUG}no-such-cup/").status_code == 404
    assert staff.get(f"{BY_SLUG}{'a' * 81}/").status_code == 404


def test_the_migration_fills_slugs_for_existing_tournaments(staff, club):
    tournament = make_tournament(staff, club, name="Old Cup")
    twin = make_tournament(staff, club, name="Old Cup")
    migration = import_module("competitions.migrations.0028_tournament_slug")
    for row in (tournament, twin):  # as if made before slugs: any distinct placeholder
        Tournament.objects.filter(pk=row["id"]).update(slug=f"x-{row['id']}")
    migration.fill_slugs(apps, None)
    both = Tournament.objects.filter(pk__in=[tournament["id"], twin["id"]])
    slugs = set(both.values_list("slug", flat=True))
    assert slugs == {"old-cup-2026", "old-cup-2026-2"}


def test_a_tournament_the_previous_release_made_without_a_slug_gets_one(staff, club):
    made = make_tournament(staff, club, name="Deploy Cup")
    # During a deploy the previous release still writes tournaments without a slug.
    Tournament.objects.filter(pk=made["id"]).update(slug=None)
    other = make_tournament(staff, club, name="Other Cup")
    Tournament.objects.filter(pk=other["id"]).update(slug=None)  # two without one don't clash
    tournament = Tournament.objects.get(pk=made["id"])
    tournament.save()
    assert tournament.slug == "deploy-cup-2026"
