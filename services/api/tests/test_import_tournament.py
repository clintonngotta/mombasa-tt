"""Copying a public tournament into the dev database: dev only, from allowed https hosts only, and the
draw comes across as it is, with where each side still to come is from."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from competitions.management.commands import import_tournament
from competitions.models import Match, Tournament
from organizations.models import Organization

pytestmark = pytest.mark.django_db
PK = "3be03139-57fa-4f73-b6c8-3accdfe4412d"
EVENT = "83129037-7842-4d36-a7c9-10afb787446e"


def side(entry=None, awaiting=""):
    return {"entry": entry, "seed": None, "awaiting": awaiting}


def person(n):
    return {
        "id": f"00000000-0000-4000-8000-00000000000{n}",
        "title": f"P{n}",
        "pool": "",
        "players": [{"id": f"10000000-0000-4000-8000-00000000000{n}", "display_name": f"P{n}"}],
    }


def match(n, stage, round_, position, a, b, group=None):
    return {
        "id": f"20000000-0000-4000-8000-00000000000{n}",
        "stage": stage,
        "group": group,
        "round": round_,
        "position": position,
        "a": a,
        "b": b,
        "status": "scheduled",
        "outcome": "",
        "games": [],
        "winner_id": None,
        "scheduled_at": None,
    }


PUBLIC = {
    f"/tournaments/{PK}/": {
        "id": PK,
        "name": "Coast Series",
        "venue": {"name": "Hall"},
        "starts_on": "2026-11-28",
        "ends_on": "2026-11-28",
        "timezone": "Africa/Nairobi",
        "status": "published",
        "events": [
            {
                "id": EVENT,
                "name": "Singles",
                "kind": "singles",
                "format": "groups_knockout",
                "best_of": 3,
                "rest_minutes": 10,
                "group_count": 2,
                "qualifiers_per_group": 1,
                "seeding": "rating",
                "status": "scheduled",
            }
        ],
    },
    f"/tournaments/{PK}/events/{EVENT}/entries/?page=1": {
        "next": None,
        "results": [{**person(n), "status": "accepted"} for n in range(1, 5)],
    },
    f"/tournaments/{PK}/events/{EVENT}/draw/": {
        "published": {
            "id": "30000000-0000-4000-8000-000000000001",
            "version": 1,
            "rules_version": "ITTF-2026-ch3",
            "rng_seed": 7,
            "groups": [{"number": 1, "name": "Group A"}, {"number": 2, "name": "Group B"}],
            "places": [
                {
                    "entry": person(n),
                    "seed": n,
                    "group": 1 + (n > 2),
                    "group_position": 1 + (n % 2 == 0),
                    "bracket_position": None,
                }
                for n in range(1, 5)
            ],
            "matches": [
                match(1, "group", 1, 1, side(person(1)), side(person(2)), group=1),
                match(2, "group", 1, 1, side(person(3)), side(person(4)), group=2),
                match(3, "knockout", 1, 1, side(awaiting="Group A winner"), side(awaiting="Group B winner")),
            ],
        }
    },
}


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(import_tournament.Fetcher, "get", lambda self, path: PUBLIC[path])


def test_it_copies_the_draw_as_it_is(settings, club, public):
    settings.DEBUG = True
    Organization.objects.filter(pk=club.pk).update(name=import_tournament.DEV_CLUB)
    for _ in range(2):  # importing again replaces the copy
        call_command("import_tournament", f"https://app.coastloopas.org/tournaments/{PK}", tables=3)
    tournament = Tournament.objects.get(pk=PK)
    assert tournament.venue.tables.count() == 3
    final = Match.objects.get(stage="knockout")
    assert (final.a_from_group, final.a_from_rank, final.b_from_group) == (1, 1, 2)
    assert Match.objects.filter(stage="group", entry_a__isnull=False).count() == 2


def test_it_is_for_development_and_allowed_hosts_only(settings, public):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DJANGO_DEBUG"):
        call_command("import_tournament", PK)
    settings.DEBUG = True
    for source in ("http://app.coastloopas.org", "https://169.254.169.254", "https://evil.example"):
        with pytest.raises(CommandError, match="Only https"):
            call_command("import_tournament", PK, source=source)
