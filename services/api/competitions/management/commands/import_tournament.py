"""Copy a tournament as the public API shows it into the development database, to try schedules and
draws on real data: its events, accepted entries, published draws (places, matches, results) and, when
given, its sessions. Ids are kept, so importing again replaces the copy. Players become local accounts
that can't log in. The copy is hosted by the dev club, so the dev club admin runs it.

Refuses to run unless DJANGO_DEBUG is on, and reads only from an https address on the allowed hosts.
"""

import json
import re
import urllib.request
from datetime import time
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from facilities.models import Table, Venue
from organizations.models import Organization

from ...drawing import group_name, round_name
from ...models import (
    DrawPlace,
    DrawVersion,
    Entry,
    EntryPlayer,
    Event,
    Match,
    ScheduleSession,
    Tournament,
)

ALLOWED_HOSTS = {"app.coastloopas.org"}
TIMEOUT = 20  # seconds for each request
MOST_BYTES = 5 * 1024 * 1024
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DEV_CLUB = "Mombasa Dev TT Club"
RANKS = {"winner": 1, "runner-up": 2}
EVENT_FIELDS = (
    "name",
    "kind",
    "format",
    "capacity",
    "best_of",
    "rest_minutes",
    "call_grace_minutes",
    "admission",
    "seeding",
    "group_count",
    "qualifiers_per_group",
    "status",
)


class Fetcher:
    def __init__(self, source: str):
        parts = urlsplit(source)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise CommandError(f"Only https addresses on {', '.join(sorted(ALLOWED_HOSTS))}.")
        self.base = f"https://{parts.hostname}/api/v1"

    def get(self, path: str) -> dict:
        request = urllib.request.Request(
            self.base + path, headers={"Accept": "application/json", "User-Agent": "coast-tt-import/1"}
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (https, allowed host)
            if urlsplit(response.geturl()).hostname not in ALLOWED_HOSTS:
                raise CommandError("The source redirected elsewhere.")
            body = response.read(MOST_BYTES + 1)
        if len(body) > MOST_BYTES:
            raise CommandError(f"{path} is larger than {MOST_BYTES} bytes.")
        return json.loads(body)

    def pages(self, path: str) -> list:
        found, page = [], 1
        while True:
            data = self.get(f"{path}?page={page}")
            found += data["results"]
            if not data.get("next"):
                return found
            page += 1


class Command(BaseCommand):
    help = "Copy a public tournament (events, entries, published draws) into the dev database. Dev only."

    def add_arguments(self, parser):
        parser.add_argument("tournament", help="The tournament's page address, or its id.")
        parser.add_argument("--source", default="https://app.coastloopas.org")
        parser.add_argument("--tables", type=int, default=5, help="Tables at the copy's venue.")
        parser.add_argument(
            "--sessions",
            help='A JSON file of sessions: [{"name", "day", "starts", "ends", "tables": ["Table 1"], '
            '"events": [event ids]}]. Staff only see them, so the public API has none.',
        )

    def handle(self, *args, tournament, source, tables, sessions, **options):
        if not settings.DEBUG:
            raise CommandError("import_tournament only runs with DJANGO_DEBUG=true.")
        found = UUID.search(tournament)
        if not found:
            raise CommandError("Give the tournament's address or id.")
        pk = found.group(0)
        fetch = Fetcher(source)
        shown = fetch.get(f"/tournaments/{pk}/")
        events = []
        for event in shown["events"]:
            base = f"/tournaments/{pk}/events/{event['id']}/"
            draw = fetch.get(base + "draw/")["published"]
            events.append((event, fetch.pages(base + "entries/"), draw))
        planned = json.loads(open(sessions).read()) if sessions else []  # noqa: SIM115
        if not 1 <= tables <= 50:
            raise CommandError("--tables is from 1 to 50.")
        with transaction.atomic():
            made = self.copy(shown, events, tables, planned)
        self.stdout.write(f"Imported {made.name}: /tournaments/{made.id}")

    def copy(self, shown: dict, events: list, table_count: int, planned: list) -> Tournament:
        club = Organization.objects.filter(name=DEV_CLUB).first()
        if club is None:
            raise CommandError("Run seed_dev first: the copy is hosted by the dev club.")
        _forget(shown["id"])
        venue_name = f"{shown['venue']['name'] if shown.get('venue') else 'Venue'} (imported)"
        venue, _ = Venue.objects.get_or_create(
            organization=club, name=venue_name, defaults={"town": "Mombasa"}
        )
        tables = {}
        for n in range(1, table_count + 1):
            table, _ = Table.objects.get_or_create(
                venue=venue, label=f"Table {n}", defaults={"position": n, "active": True}
            )
            tables[table.label] = table
        tournament = Tournament.objects.create(
            id=shown["id"],
            organization=club,
            venue=venue,
            name=shown["name"],
            description=shown.get("description", ""),
            starts_on=shown["starts_on"],
            ends_on=shown["ends_on"],
            timezone=shown["timezone"],
            status=shown["status"],
            published_at=shown.get("published_at"),
            schedule_notice_minutes=shown.get("schedule_notice_minutes", 15),
        )
        for event_shown, entries, draw in events:
            event = Event.objects.create(
                id=event_shown["id"],
                tournament=tournament,
                **{key: event_shown[key] for key in EVENT_FIELDS if key in event_shown},
            )
            for entry in entries:
                _entry(event, entry)
            if draw:
                _draw(event, draw)
        for session in planned:
            made = ScheduleSession.objects.create(
                tournament=tournament,
                name=session.get("name", ""),
                day=session["day"],
                starts=time.fromisoformat(session["starts"]),
                ends=time.fromisoformat(session["ends"]),
            )
            made.tables.set([tables[label] for label in session["tables"] if label in tables])
            made.events.set(Event.objects.filter(tournament=tournament, id__in=session.get("events", [])))
        return tournament


def _forget(pk: str) -> None:
    """The earlier copy, if any: matches and places first, since they keep entries from going."""
    Match.objects.filter(draw__event__tournament_id=pk).delete()
    DrawPlace.objects.filter(draw__event__tournament_id=pk).delete()
    Tournament.objects.filter(pk=pk).delete()


def _player(shown: dict) -> User:
    user, created = User.objects.get_or_create(
        id=shown["id"],
        defaults={"email": f"imported-{shown['id']}@import.invalid", "display_name": shown["display_name"]},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _entry(event: Event, shown: dict) -> Entry:
    entry, created = Entry.objects.get_or_create(
        id=shown["id"],
        defaults={
            "event": event,
            "status": shown.get("status") or Entry.Status.ACCEPTED,
            "team_name": shown.get("team_name", ""),
            "pool": shown.get("pool", ""),
        },
    )
    if created:
        for position, player in enumerate(shown["players"]):
            EntryPlayer.objects.create(
                entry=entry,
                event=event,
                user=_player(player),
                position=position,
                live=entry.status in Entry.LIVE,
            )
    return entry


def _draw(event: Event, shown: dict) -> None:
    draw = DrawVersion.objects.create(
        id=shown["id"],
        event=event,
        version=shown["version"],
        status=DrawVersion.Status.PUBLISHED,
        rules_version=shown["rules_version"],
        rng_seed=shown["rng_seed"],
        format=event.format,
        group_count=event.group_count,
        qualifiers_per_group=event.qualifiers_per_group,
        published_at=shown.get("published_at"),
    )
    for place in shown["places"]:
        DrawPlace.objects.create(
            draw=draw,
            entry=_entry(event, {**place["entry"], "status": Entry.Status.ACCEPTED}),
            seed=place["seed"],
            group=place["group"],
            group_position=place["group_position"],
            bracket_position=place["bracket_position"],
        )
    rounds = max((m["round"] for m in shown["matches"] if m["stage"] == Match.Stage.KNOCKOUT), default=0)
    groups = {group_name(group["number"]): group["number"] for group in shown["groups"]}
    made: dict = {}
    for match in sorted(shown["matches"], key=lambda m: (m["stage"] == Match.Stage.KNOCKOUT, m["round"])):
        sides = {}
        for side in ("a", "b"):
            sides.update(_side(side, match[side], made, groups, rounds))
        made[match["id"]] = Match.objects.create(
            id=match["id"],
            draw=draw,
            stage=match["stage"],
            group=match["group"],
            round=match["round"],
            position=match["position"],
            status=match["status"],
            outcome=match.get("outcome", ""),
            games=match.get("games") or [],
            winner_id=match.get("winner_id"),
            scheduled_at=match.get("scheduled_at"),
            **sides,
        )


def _side(side: str, shown: dict | None, made: dict, groups: dict, rounds: int) -> dict:
    """The model fields of one side: its entry, or where it comes from ("Group A winner", "Winner of
    quarter-final 2"), read back from the words the draw shows."""
    if shown is None:
        return {}
    if shown["entry"]:
        return {f"entry_{side}_id": shown["entry"]["id"]}
    awaiting = shown["awaiting"]
    for name, number in groups.items():
        if awaiting.startswith(name + " "):
            rank = awaiting[len(name) + 1 :]
            rank = RANKS.get(rank) or int(rank.removeprefix("number "))
            return {f"{side}_from_group": number, f"{side}_from_rank": rank}
    for match in made.values():
        if match.stage != Match.Stage.KNOCKOUT:
            continue
        if awaiting == f"Winner of {round_name(match.round, rounds).lower()} {match.position}":
            return {f"feeder_{side}": match}
    raise CommandError(f"Can't tell where “{awaiting}” comes from.")
