"""Tournament and event setup and lifecycle (REQ-007, EVAL-007, TASK-017)."""

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from competitions.models import Event, LifecycleEntry, Tournament
from organizations.models import Organization
from organizations.permissions import RoleKey

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, code, create_club
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
TOURNAMENTS = "/api/v1/tournaments/"
SINGLES = {"name": "Men's singles", "kind": "singles", "format": "knockout"}


def url(tournament=None, action="", event=None):
    path = TOURNAMENTS + (f"{tournament['id']}/" if tournament else "")
    if event is not None:
        path += "events/" + (f"{event['id']}/" if event else "")
    return path + (f"{action}/" if action else "")


@pytest.fixture
def venue(staff, club):
    return make_venue(staff, club)


def make_tournament(staff, club, venue=None, **extra) -> dict:
    body = {"name": "Coast Open", "starts_on": "2026-12-05", "ends_on": "2026-12-06", **extra}
    if venue:
        body["venue_id"] = venue["id"]
    response = staff.post(f"{ORGS}{club.id}/tournaments/", body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def add_event(staff, tournament, **body) -> dict:
    response = staff.post(url(tournament, event=False), {**SINGLES, **body}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def do(client, tournament, action, event=None, **body) -> dict:
    response = client.post(url(tournament, action, event), body, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.fixture
def draft(staff, club, venue):
    return add_event(staff, make_tournament(staff, club, venue))


@pytest.fixture
def running(staff, draft):
    do(staff, draft, "publish")
    return do(staff, draft, "start")


def test_events_of_every_type_and_format_are_configured_in_a_draft(staff, club, venue):
    tournament = make_tournament(staff, club, venue, description="  Annual open.  ")
    assert tournament["status"] == "draft" and tournament["description"] == "Annual open."
    assert tournament["venue"] == {
        "id": venue["id"],
        "name": "Makadara Hall",
        "town": "Mombasa",
        "address": "",
        "directions": "",
        "latitude": None,
        "longitude": None,
    }
    assert tournament["organization"] == {
        "id": str(club.id),
        "name": club.name,
        "town": club.town,
        "country": club.country,
        "region": club.region,
    }

    set_up = [
        {"name": "Men's singles", "kind": "singles", "format": "knockout"},
        {"name": "Women's singles", "kind": "singles", "format": "round_robin", "best_of": 3},
        {
            "name": "Open doubles",
            "kind": "doubles",
            "format": "groups_knockout",
            "group_count": 4,
            "qualifiers_per_group": 2,
            "capacity": 16,
            "best_of": 7,
            "rest_minutes": 15,
            "seeding": "manual",
            "entry_fee": {"amount_minor": 50000, "currency": "KES"},
            "registration_opens_at": "2026-11-20T08:00:00+03:00",
            "registration_closes_at": "2026-12-03T18:00:00+03:00",
        },
        {"name": "Club teams", "kind": "team", "format": "round_robin", "capacity": 6},
    ]
    for body in set_up:
        tournament = add_event(staff, tournament, **body)
    events = tournament["events"]
    assert [e["name"] for e in events] == [e["name"] for e in set_up]

    # Defaults (REQ-012, REQ-014): best of five, ten minutes' rest, seeded by rating, no fee, no limit.
    first = events[0]
    assert (first["best_of"], first["rest_minutes"], first["seeding"], first["capacity"]) == (
        5,
        10,
        "rating",
        None,
    )
    assert first["entry_fee"] == {"amount_minor": 0, "currency": "KES"}
    assert (first["status"], first["revision"]) == ("scheduled", 1)
    assert (first["group_count"], first["qualifiers_per_group"]) == (None, None)

    doubles = events[2]
    assert (doubles["group_count"], doubles["qualifiers_per_group"], doubles["capacity"]) == (4, 2, 16)
    assert doubles["entry_fee"] == {"amount_minor": 50000, "currency": "KES"}

    # Changing the set-up counts a revision; saving the same values doesn't.
    changed = staff.patch(url(tournament, event=doubles), {"capacity": 24}, format="json").json()
    assert (changed["events"][2]["capacity"], changed["events"][2]["revision"]) == (24, 2)
    same = staff.patch(url(tournament, event=doubles), {"capacity": 24}, format="json").json()
    assert same["events"][2]["revision"] == 2

    # Leaving the groups format drops the group settings instead of keeping stale ones.
    flat = staff.patch(url(tournament, event=doubles), {"format": "knockout"}, format="json").json()
    assert (flat["events"][2]["group_count"], flat["events"][2]["qualifiers_per_group"]) == (None, None)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"best_of": 4}, "best_of"),
        ({"capacity": 1}, "capacity"),
        ({"kind": "mixed"}, "kind"),
        ({"format": "swiss"}, "format"),
        ({"name": "  "}, "name"),
        ({"rest_minutes": -5}, "rest_minutes"),
        ({"format": "groups_knockout"}, "group_count"),
        ({"format": "groups_knockout", "group_count": 4}, "qualifiers_per_group"),
        (
            {"format": "groups_knockout", "group_count": 4, "qualifiers_per_group": 2, "capacity": 8},
            "capacity",
        ),
        ({"entry_fee": {"amount_minor": -1, "currency": "KES"}}, "entry_fee"),
        ({"entry_fee": {"amount_minor": 100, "currency": "shillings"}}, "entry_fee"),
        (
            {
                "registration_opens_at": "2026-12-01T10:00:00Z",
                "registration_closes_at": "2026-12-01T09:00:00Z",
            },
            "registration_closes_at",
        ),
    ],
)
def test_event_setup_is_validated(staff, club, venue, body, field):
    tournament = make_tournament(staff, club, venue)
    response = staff.post(url(tournament, event=False), {**SINGLES, **body}, format="json")
    assert response.status_code == 400, response.json()
    assert field in response.json()["fields"]
    assert Event.objects.count() == 0


def test_tournament_setup_is_validated(staff, club, venue):
    create = f"{ORGS}{club.id}/tournaments/"
    backwards = staff.post(
        create, {"name": "X", "starts_on": "2026-12-06", "ends_on": "2026-12-05"}, format="json"
    )
    assert "ends_on" in backwards.json()["fields"]
    zone = staff.post(
        create,
        {"name": "X", "starts_on": "2026-12-05", "ends_on": "2026-12-05", "timezone": "Mombasa"},
        format="json",
    )
    assert "timezone" in zone.json()["fields"]

    # Another organization's venue, or one switched off, can't host it.
    rival = create_club(make_user("rival@example.com"), "Nyali Loop")
    theirs = make_venue(logged_in(rival.memberships.get().user), rival, "Nyali Gym")
    off = make_venue(staff, club, "Old Hall")
    staff.patch(f"{ORGS}{club.id}/venues/{off['id']}/", {"active": False}, format="json")
    for bad in (theirs, off):
        body = {"name": "X", "starts_on": "2026-12-05", "ends_on": "2026-12-05", "venue_id": bad["id"]}
        assert "venue_id" in staff.post(create, body, format="json").json()["fields"]
    assert Tournament.objects.count() == 0

    # A tournament keeps a venue that is switched off later.
    tournament = make_tournament(staff, club, venue)
    staff.patch(f"{ORGS}{club.id}/venues/{venue['id']}/", {"active": False}, format="json")
    kept = staff.patch(url(tournament), {"venue_id": venue["id"], "name": "Coast Open 2026"}, format="json")
    assert kept.status_code == 200 and kept.json()["venue"]["id"] == venue["id"]


def test_regional_tournament_uses_the_hosts_location_and_can_be_filtered(staff, club, venue):
    from .helpers import make_official

    refused = staff.post(
        f"/api/v1/organizations/{club.id}/tournaments/",
        {"name": "Coast Regional", "starts_on": "2026-12-05", "ends_on": "2026-12-05", "scope": "regional"},
        format="json",
    )
    assert refused.status_code == 400 and "scope" in refused.json()["fields"]
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    tournament = make_tournament(staff, club, venue, scope="regional")
    assert tournament["scope"] == "regional" and tournament["organization"]["region"] == "Mombasa"
    tournament = add_event(staff, tournament, name="Singles", kind="singles", format="knockout")
    assert staff.post(url(tournament, "publish"), {}, format="json").status_code == 403
    assert do(staff, tournament, "approval/request")["approval_status"] == "pending"
    official = make_user("official@example.com")
    other = make_user("outside@example.com")
    make_official(official, "KE", "Mombasa")
    make_official(other, "KE", "Kilifi")
    denied = logged_in(other).post(url(tournament, "publish"), {}, format="json")
    assert denied.status_code == 404
    tournament = do(logged_in(official), tournament, "publish")
    assert tournament["approval_status"] == "approved"
    assert [row["id"] for row in staff.get("/api/v1/tournaments/?scope=regional").json()["results"]] == [
        tournament["id"]
    ]
    assert staff.get("/api/v1/tournaments/?scope=international").json()["results"] == []
    do(staff, tournament, "start")
    changed = staff.patch(url(tournament), {"scope": "national"}, format="json")
    assert changed.status_code == 409 and changed.json()["code"] == "structure_frozen"


def test_tournament_fee_defaults_new_events_and_can_be_overridden(staff, club, venue):
    fee = {"amount_minor": 50000, "currency": "KES"}
    tournament = make_tournament(staff, club, venue, registration_fee=fee)
    assert tournament["registration_fee"] == fee
    tournament = add_event(staff, tournament, name="Singles")
    assert tournament["events"][0]["entry_fee"] == fee
    tournament = add_event(staff, tournament, name="Doubles", kind="doubles", entry_fee={"amount_minor": 0})
    assert tournament["events"][1]["entry_fee"]["amount_minor"] == 0


def test_dates_are_calendar_days_in_the_organizations_timezone(staff, admin, venue, club):
    # Tournaments take the host organization's timezone unless told otherwise.
    assert make_tournament(staff, club, venue)["timezone"] == "Africa/Nairobi"
    response = staff.post(
        ORGS, {"name": "Kiwi Spinners", "town": "Auckland", "timezone": "Pacific/Auckland"}, format="json"
    )
    far = Organization.objects.get(pk=response.json()["id"])
    assert far.timezone == "Pacific/Auckland"
    tournament = make_tournament(staff, far, starts_on="2026-12-31", ends_on="2027-01-01")
    # Days are stored as days: no shift to the server's zone or to UTC, 13 hours away.
    assert (tournament["timezone"], tournament["starts_on"], tournament["ends_on"]) == (
        "Pacific/Auckland",
        "2026-12-31",
        "2027-01-01",
    )
    stored = Tournament.objects.get(pk=tournament["id"])
    assert (stored.starts_on.isoformat(), stored.ends_on.isoformat()) == ("2026-12-31", "2027-01-01")

    # Instants round-trip exactly whatever offset they were sent with.
    sent = "2026-12-30T18:00:00+13:00"
    event = add_event(staff, tournament, registration_closes_at=sent)["events"][0]
    assert datetime.fromisoformat(event["registration_closes_at"]) == datetime.fromisoformat(sent)
    assert Event.objects.get().registration_closes_at == datetime.fromisoformat("2026-12-30T05:00:00+00:00")

    moved = staff.patch(url(tournament), {"timezone": "Africa/Nairobi"}, format="json").json()
    assert (moved["timezone"], moved["starts_on"]) == ("Africa/Nairobi", "2026-12-31")


def test_lifecycle_runs_draft_published_in_progress_completed(staff, admin, draft):
    event = draft["events"][0]
    # Nothing can be skipped.
    for action in ("start", "complete"):
        early = staff.post(url(draft, action), {}, format="json")
        assert early.status_code == 409 and code(early) == "invalid_transition"
    early = staff.post(url(draft, "start", event), {}, format="json")
    assert early.status_code == 409 and code(early) == "tournament_not_started"

    published = do(staff, draft, "publish")
    assert published["status"] == "published" and published["published_at"]
    assert staff.post(url(draft, "publish"), {}, format="json").status_code == 409
    assert staff.post(url(draft, "start", event), {}, format="json").status_code == 409

    started = do(staff, draft, "start")
    assert started["status"] == "in_progress" and started["started_at"]

    # The tournament can't be completed while an event is still to be played or is being played.
    def blocked():
        response = staff.post(url(draft, "complete"), {}, format="json")
        return response.status_code == 409 and code(response) == "events_unfinished"

    assert blocked()
    assert staff.post(url(draft, "complete", event), {}, format="json").status_code == 409  # not started
    assert do(staff, draft, "start", event)["events"][0]["status"] == "in_progress"
    assert blocked()
    do(staff, draft, "complete", event)

    done = do(staff, draft, "complete")
    assert done["status"] == "completed" and done["completed_at"]
    assert done["events"][0]["status"] == "completed" and done["events"][0]["completed_at"]

    # Completed is final: no more transitions, edits or events.
    for action in ("publish", "start", "complete"):
        assert staff.post(url(draft, action), {}, format="json").status_code == 409
    assert staff.post(url(draft, "cancel"), {"reason": "Too late"}, format="json").status_code == 409
    for response in (
        staff.patch(url(draft), {"name": "Renamed"}, format="json"),
        staff.post(url(draft, event=False), SINGLES, format="json"),
        staff.patch(url(draft, event=event), {"capacity": 8}, format="json"),
    ):
        assert response.status_code == 409 and code(response) == "tournament_closed"

    history = staff.get(url(draft, "history")).json()
    assert [(h["action"], h["event_name"], h["actor_name"]) for h in history] == [
        ("published", "", "Club Admin"),
        ("started", "", "Club Admin"),
        ("event_started", "Men's singles", "Club Admin"),
        ("event_completed", "Men's singles", "Club Admin"),
        ("completed", "", "Club Admin"),
    ]
    # The published configuration can be identified later: the entry holds it as it was.
    assert history[0]["snapshot"]["status"] == "published"
    assert [(e["name"], e["format"], e["revision"]) for e in history[0]["snapshot"]["events"]] == [
        ("Men's singles", "knockout", 1)
    ]


def test_publishing_needs_a_venue_and_an_event(staff, club, venue):
    bare = make_tournament(staff, club)
    response = staff.post(url(bare, "publish"), {}, format="json")
    assert response.status_code == 409 and code(response) == "not_ready"
    assert "a venue and at least one event" in response.json()["message"]
    staff.patch(url(bare), {"venue_id": venue["id"]}, format="json")
    assert "at least one event" in staff.post(url(bare, "publish"), {}, format="json").json()["message"]
    add_event(staff, bare)
    assert do(staff, bare, "publish")["status"] == "published"


def test_structure_is_frozen_once_an_event_starts(staff, running):
    first = running["events"][0]
    second = add_event(
        staff,
        running,
        name="Open doubles",
        kind="doubles",
        format="groups_knockout",
        group_count=2,
        qualifiers_per_group=2,
    )["events"][1]
    do(staff, running, "start", first)

    for body in (
        {"format": "round_robin"},
        {"kind": "doubles"},
        {"seeding": "none"},
        {"format": "groups_knockout", "group_count": 2, "qualifiers_per_group": 1},
        {"name": "Renamed", "format": "round_robin"},  # nothing is applied when part of it is refused
    ):
        response = staff.patch(url(running, event=first), body, format="json")
        assert response.status_code == 409 and code(response) == "structure_frozen", body
    stored = Event.objects.get(pk=first["id"])
    assert (stored.name, stored.format, stored.kind, stored.best_of, stored.revision) == (
        "Men's singles",
        "knockout",
        "singles",
        5,
        1,
    )

    # What isn't structure can still change, and repeating the current structure is not a change.
    ok = staff.patch(
        url(running, event=first), {"name": "Men's open", "capacity": 32, "format": "knockout"}, format="json"
    )
    assert ok.status_code == 200 and ok.json()["events"][0]["name"] == "Men's open"

    # An event that hasn't started is still open, qualification included.
    other = staff.patch(
        url(running, event=second), {"qualifiers_per_group": 1, "group_count": 4}, format="json"
    )
    assert other.status_code == 200
    do(staff, running, "start", second)
    for body in ({"qualifiers_per_group": 2}, {"group_count": 2}, {"format": "knockout"}):
        response = staff.patch(url(running, event=second), body, format="json")
        assert response.status_code == 409 and code(response) == "structure_frozen", body
    assert Event.objects.get(pk=second["id"]).qualifiers_per_group == 1

    # A finished event doesn't change at all.
    do(staff, running, "complete", first)
    closed = staff.patch(url(running, event=first), {"name": "Again"}, format="json")
    assert closed.status_code == 409 and code(closed) == "event_closed"

    # The tournament's timezone is fixed once play has begun; its dates may still move.
    zone = staff.patch(url(running), {"timezone": "Africa/Kampala"}, format="json")
    assert zone.status_code == 409 and code(zone) == "structure_frozen"
    assert (
        staff.patch(url(running), {"ends_on": "2026-12-07"}, format="json").json()["ends_on"] == "2026-12-07"
    )


def test_cancellation_is_terminal_and_audited(staff, admin, running):
    first = running["events"][0]
    second = add_event(staff, running, name="Open doubles", kind="doubles")["events"][1]
    do(staff, running, "start", first)
    do(staff, running, "complete", first)

    # A reason is required.
    for body in ({}, {"reason": "  "}):
        assert staff.post(url(running, "cancel"), body, format="json").status_code == 400
        assert staff.post(url(running, "cancel", second), body, format="json").status_code == 400
    assert Tournament.objects.get().status == "in_progress"

    cancelled = do(staff, running, "cancel", reason="Hall flooded overnight")
    assert (cancelled["status"], cancelled["cancel_reason"]) == ("cancelled", "Hall flooded overnight")
    assert cancelled["cancelled_at"]
    # Finished events keep their outcome; the rest are cancelled with the tournament.
    assert [(e["status"], e["cancel_reason"]) for e in cancelled["events"]] == [
        ("completed", ""),
        ("cancelled", "Hall flooded overnight"),
    ]

    for action in ("publish", "start", "complete"):
        assert staff.post(url(running, action), {}, format="json").status_code == 409
    again = staff.post(url(running, "cancel"), {"reason": "Twice"}, format="json")
    assert again.status_code == 409 and code(again) == "invalid_transition"
    assert staff.patch(url(running), {"name": "Back on"}, format="json").status_code == 409
    assert staff.delete(url(running)).status_code == 409

    last = staff.get(url(running, "history")).json()[-1]
    assert (last["action"], last["actor_name"], last["reason"]) == (
        "cancelled",
        "Club Admin",
        "Hall flooded overnight",
    )
    assert LifecycleEntry.objects.filter(action="cancelled", actor=admin).count() == 1


def test_one_event_can_be_cancelled_and_only_drafts_lose_events(staff, draft):
    extra = add_event(staff, draft, name="Open doubles", kind="doubles")["events"][1]
    # In a draft an event is simply removed.
    removed = staff.delete(url(draft, event=extra))
    assert removed.status_code == 200 and len(removed.json()["events"]) == 1

    extra = add_event(staff, draft, name="Open doubles", kind="doubles")["events"][1]
    do(staff, draft, "publish")
    kept = staff.delete(url(draft, event=extra))
    assert kept.status_code == 409 and code(kept) == "already_published"
    cancelled = do(staff, draft, "cancel", extra, reason="Too few pairs")
    assert [(e["status"], e["cancel_reason"]) for e in cancelled["events"]] == [
        ("scheduled", ""),
        ("cancelled", "Too few pairs"),
    ]
    assert staff.post(url(draft, "cancel", extra), {"reason": "Again"}, format="json").status_code == 409

    # With its only other event cancelled too there is nothing to start.
    do(staff, draft, "cancel", draft["events"][0], reason="Too few players")
    nothing = staff.post(url(draft, "start"), {}, format="json")
    assert nothing.status_code == 409 and code(nothing) == "not_ready"


def test_only_competition_staff_of_the_host_change_a_tournament(club, staff, draft, venue):
    event = draft["events"][0]
    member = logged_in(add_member(club, make_user("juma@example.com")).user)
    committee = logged_in(add_member(club, make_user("com@example.com"), RoleKey.COMMITTEE).user)
    outsider = logged_in(make_user("out@example.com"))
    rival = create_club(make_user("rival@example.com"), "Nyali Loop")
    rival_staff = logged_in(rival.memberships.get().user)
    others = (member, committee, outsider, rival_staff)

    def attempts(client):
        return [
            client.patch(url(draft), {"name": "Taken over"}, format="json"),
            client.delete(url(draft)),
            client.post(url(draft, "publish"), {}, format="json"),
            client.post(url(draft, "start"), {}, format="json"),
            client.post(url(draft, "complete"), {}, format="json"),
            client.post(url(draft, "cancel"), {"reason": "Mine now"}, format="json"),
            client.get(url(draft, "history")),
            client.post(url(draft, event=False), SINGLES, format="json"),
            client.patch(url(draft, event=event), {"capacity": 4}, format="json"),
            client.delete(url(draft, event=event)),
            client.post(url(draft, "start", event), {}, format="json"),
            client.post(url(draft, "complete", event), {}, format="json"),
            client.post(url(draft, "cancel", event), {"reason": "Mine now"}, format="json"),
        ]

    # A draft doesn't exist for anyone but the host's competition staff.
    for client in others:
        assert client.get(url(draft)).status_code == 404
        assert {r.status_code for r in attempts(client)} == {404}
        assert client.get(f"{ORGS}{club.id}/tournaments/").status_code == 403
        create = client.post(
            f"{ORGS}{club.id}/tournaments/",
            {"name": "X", "starts_on": "2026-12-05", "ends_on": "2026-12-05"},
            format="json",
        )
        assert create.status_code == 403
        assert client.get(TOURNAMENTS).json()["count"] == 0
    assert BrowserClient().get(url(draft)).status_code == 404  # signed out, a draft doesn't exist
    assert BrowserClient().get(TOURNAMENTS).json()["count"] == 0  # the public list has no drafts

    # Published: everyone signed in can read it, and still only staff can change it.
    do(staff, draft, "publish")
    for client in others:
        assert client.get(url(draft)).json()["name"] == "Coast Open"
        assert [t["id"] for t in client.get(TOURNAMENTS).json()["results"]] == [draft["id"]]
        assert {r.status_code for r in attempts(client)} == {403}
    stored = Tournament.objects.get()
    assert (stored.name, stored.status, stored.events.count()) == ("Coast Open", "published", 1)
    assert Event.objects.get().capacity is None

    # Running competitions here doesn't reach another organization's tournaments.
    theirs = add_event(rival_staff, make_tournament(rival_staff, rival, name="Nyali Cup"))
    assert staff.get(url(theirs)).status_code == 404
    assert staff.patch(url(theirs), {"name": "Ours"}, format="json").status_code == 404
    # ... nor lets an event id be used through the wrong tournament.
    assert (
        staff.patch(url(draft, event=theirs["events"][0]), {"capacity": 4}, format="json").status_code == 404
    )

    # The assistant captain template runs competitions without being an admin.
    assistant = logged_in(add_member(club, make_user("ass@example.com"), RoleKey.ASSISTANT_CAPTAIN).user)
    assert assistant.patch(url(draft), {"name": "Coast Open 2026"}, format="json").status_code == 200
    assert do(assistant, draft, "start")["status"] == "in_progress"
    assert [t["name"] for t in assistant.get(f"{ORGS}{club.id}/tournaments/").json()["results"]] == [
        "Coast Open 2026"
    ]


def test_listing_shows_published_tournaments_by_time_and_host(staff, club, venue):
    today = timezone.localdate()

    def dated(name, start, days=0, **extra):
        made = make_tournament(
            staff,
            club,
            venue,
            name=name,
            starts_on=(today + timedelta(days=start)).isoformat(),
            ends_on=(today + timedelta(days=start + days)).isoformat(),
            **extra,
        )
        return add_event(staff, made)

    dated("Draft Cup", 3)
    soon = do(staff, dated("Soon Cup", 3), "publish")
    later = do(staff, dated("Later Cup", 30), "publish")
    now = dated("Running Cup", -1, days=2)
    do(staff, now, "publish")
    do(staff, now, "start")
    ended = do(staff, dated("Ended Cup", -20), "publish")
    off = dated("Cancelled Cup", 10)
    do(staff, off, "publish")
    do(staff, off, "cancel", reason="No hall")

    viewer = logged_in(make_user("viewer@example.com"))

    def names(query=""):
        return [t["name"] for t in viewer.get(f"{TOURNAMENTS}{query}").json()["results"]]

    assert names("?when=upcoming") == ["Running Cup", "Soon Cup", "Later Cup"]
    assert names("?when=past") == ["Cancelled Cup", "Ended Cup"]
    assert set(names()) == {"Running Cup", "Soon Cup", "Later Cup", "Cancelled Cup", "Ended Cup"}
    assert names("?search=later") == ["Later Cup"]
    assert names("?search=draft") == []
    assert len(names(f"?organization={club.id}")) == 5
    rival = create_club(make_user("rival@example.com"), "Nyali Loop")
    assert names(f"?organization={rival.id}") == []
    assert viewer.get(f"{TOURNAMENTS}?organization=nope").status_code == 400
    assert {soon["status"], later["status"], ended["status"]} == {"published"}


def test_a_published_tournament_keeps_its_venue_and_records_every_edit(staff, admin, draft, venue):
    assert staff.patch(url(draft), {"venue_id": None}, format="json").json()["venue"] is None
    staff.patch(url(draft), {"venue_id": venue["id"]}, format="json")
    do(staff, draft, "publish")

    response = staff.patch(url(draft), {"venue_id": None}, format="json")
    assert response.status_code == 400 and "venue_id" in response.json()["fields"]

    # A change to what was published goes on the record with the configuration it produced.
    assert staff.patch(url(draft), {"name": "Coast Open 2026"}, format="json").status_code == 200
    staff.patch(url(draft), {"name": "Coast Open 2026"}, format="json")  # nothing changed: no entry
    history = staff.get(url(draft, "history")).json()
    assert [entry["action"] for entry in history] == ["published", "updated"]
    assert history[1]["actor_name"] == admin.display_name
    assert history[1]["snapshot"]["name"] == "Coast Open 2026"


def test_registration_closes_by_the_last_day_in_the_tournaments_timezone(staff, draft):
    event = draft["events"][0]
    # The last day is 2026-12-06 in Nairobi: 23:30 there is still that day, 00:30 the next is not.
    ok = staff.patch(
        url(draft, event=event), {"registration_closes_at": "2026-12-06T23:30:00+03:00"}, format="json"
    )
    assert ok.status_code == 200, ok.json()
    for attempt in (
        staff.patch(
            url(draft, event=event), {"registration_closes_at": "2026-12-07T00:30:00+03:00"}, format="json"
        ),
        staff.post(
            url(draft, event=False),
            {**SINGLES, "name": "Late", "registration_closes_at": "2026-12-07T00:30:00+03:00"},
            format="json",
        ),
    ):
        assert attempt.status_code == 400 and "registration_closes_at" in attempt.json()["fields"]


def test_an_event_nobody_has_seen_is_deleted_not_cancelled(staff, draft):
    response = staff.post(url(draft, "cancel", draft["events"][0]), {"reason": "Too few"}, format="json")
    assert response.status_code == 409 and code(response) == "not_published"


def test_asking_to_change_frozen_groups_is_refused_even_when_they_would_be_dropped(staff, running):
    event = running["events"][0]
    do(staff, running, "start", event)
    response = staff.patch(url(running, event=event), {"group_count": 4}, format="json")
    assert response.status_code == 409 and code(response) == "structure_frozen"
