"""The events listing and external events (REQ-042, EVAL-042; TASK-080)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from competitions.models import DrawVersion, Entry
from events.models import ExternalEvent, LinkReport
from organizations.models import Role

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, create_club
from .test_tournaments import add_event, do, make_tournament
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
EVENTS = "/api/v1/events/"


def day(offset=0):
    return (timezone.now() + timedelta(days=offset)).date().isoformat()


@pytest.fixture
def curator():
    user = make_user("curator@example.com", display_name="Curator")
    user.is_superuser = True
    user.save()
    return logged_in(user)


@pytest.fixture
def ours(club, staff):
    venue = make_venue(staff, club, name="Makadara Hall")
    cup = make_tournament(
        staff, club, venue, name="Coast Open", starts_on=day(10), ends_on=day(11), timezone="Africa/Nairobi"
    )
    add_event(staff, cup)
    do(staff, cup, "publish")
    return cup


@pytest.fixture
def theirs():
    other_admin = make_user("other@example.com", display_name="Other admin")
    other = create_club(other_admin, name="Kisumu Spinners")
    other_staff = logged_in(other_admin)
    venue = make_venue(other_staff, other, name="Kisumu Hall")
    cup = make_tournament(
        other_staff,
        other,
        venue,
        name="Lake Open",
        starts_on=day(20),
        ends_on=day(20),
        timezone="Africa/Nairobi",
    )
    add_event(other_staff, cup, kind="doubles")
    do(other_staff, cup, "publish")
    return cup


def submit(client, club, expect=201, **body):
    payload = {
        "name": "Nairobi Classic",
        "organizer": "Nairobi TT Association",
        "starts_on": day(5),
        "ends_on": day(6),
        "town": "Nairobi",
        "categories": ["singles", "juniors"],
        "info_url": "https://nairobitt.example.org/classic",
        **body,
    }
    response = client.post(f"{ORGS}{club.id}/external-events/", payload, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def names(client, **params):
    return [e["name"] for e in client.get(EVENTS, params).json()]


def test_the_public_sees_coast_events_and_approved_external_ones(staff, club, ours, theirs, curator):
    public = BrowserClient()
    assert names(public) == ["Coast Open", "Lake Open"]
    made = submit(staff, club)
    assert made["review"] == "pending"
    # Members of the submitting club see it at once, awaiting review; nobody else does.
    member = make_user("member@example.com")
    add_member(club, member)
    listed = logged_in(member).get(EVENTS).json()
    assert [(e["name"], e["review"]) for e in listed] == [
        ("Nairobi Classic", "pending"),
        ("Coast Open", None),
        ("Lake Open", None),
    ]
    assert "Nairobi Classic" not in names(public)
    assert "Nairobi Classic" not in names(logged_in(make_user("x@example.com")))
    # The curator approves; now everyone sees it, with its link's domain.
    queue = curator.get("/api/v1/external-events/review/").json()
    assert [e["name"] for e in queue] == ["Nairobi Classic"]
    curator.post(f"/api/v1/external-events/{made['id']}/approve/", {}, format="json")
    shown = [e for e in public.get(EVENTS).json() if e["kind"] == "external"][0]
    assert (shown["info_domain"], shown["categories"]) == ("nairobitt.example.org", ["singles", "juniors"])
    # External events never gain draws, entries or ratings: they aren't tournaments at all.
    assert not Entry.objects.filter(event__tournament__name="Nairobi Classic").exists()
    assert not DrawVersion.objects.filter(event__tournament__name="Nairobi Classic").exists()


def test_only_announcement_staff_submit_and_only_curators_review(staff, club, curator):
    member = make_user("member@example.com")
    add_member(club, member)
    assert submit(logged_in(member), club, expect=403)
    writer_role = Role.objects.create(organization=club, name="Comms", permissions=["announcements.manage"])
    writer = make_user("writer@example.com")
    add_member(club, writer, writer_role)
    made = submit(logged_in(writer), club)
    assert staff.post(f"/api/v1/external-events/{made['id']}/approve/", {}, format="json").status_code == 403
    assert curator.post(f"/api/v1/external-events/{made['id']}/reject/", {}, format="json").status_code == 400
    rejected = curator.post(
        f"/api/v1/external-events/{made['id']}/reject/", {"note": "Duplicate"}, format="json"
    ).json()
    assert (rejected["review"], rejected["review_note"]) == ("rejected", "Duplicate")
    # Editing details sends it back for review; cancelling doesn't.
    edited = staff.patch(
        f"{ORGS}{club.id}/external-events/{made['id']}/", {"venue": "Kasarani"}, format="json"
    ).json()
    assert edited["review"] == "pending"
    curator.post(f"/api/v1/external-events/{made['id']}/approve/", {}, format="json")
    cancelled = staff.patch(
        f"{ORGS}{club.id}/external-events/{made['id']}/", {"status": "cancelled"}, format="json"
    ).json()
    assert (cancelled["status"], cancelled["review"]) == ("cancelled", "approved")
    assert [(e["name"], e["status"]) for e in BrowserClient().get(EVENTS).json()] == [
        ("Nairobi Classic", "cancelled")
    ]


def test_links_must_be_https_on_a_public_host(staff, club):
    for bad in (
        "http://nairobitt.example.org",
        "https://localhost/x",
        "https://10.0.0.1/live",
        "javascript:alert(1)",
    ):
        refused = submit(staff, club, expect=400, live_url=bad)
        assert "live_url" in refused["fields"], bad
    assert "info_url" in submit(staff, club, expect=400, info_url="ftp://files.example.org")["fields"]


def test_live_follows_the_dates_or_the_organizer_and_shows_the_stream(staff, club, curator):
    now = submit(
        staff,
        club,
        name="Today Cup",
        starts_on=day(0),
        ends_on=day(0),
        live_url="https://www.youtube.com/live/abc",
    )
    later = submit(
        staff, club, name="Later Cup", starts_on=day(30), ends_on=day(30), live_url="https://twitch.tv/later"
    )
    for made in (now, later):
        curator.post(f"/api/v1/external-events/{made['id']}/approve/", {}, format="json")
    listed = {e["name"]: e for e in BrowserClient().get(EVENTS).json()}
    assert (
        listed["Today Cup"]["live"],
        listed["Today Cup"]["live_url"],
        listed["Today Cup"]["live_domain"],
    ) == (
        True,
        "https://www.youtube.com/live/abc",
        "youtube.com",
    )
    assert (listed["Later Cup"]["live"], listed["Later Cup"]["live_url"]) == (False, "")
    staff.post(f"{ORGS}{club.id}/external-events/{later['id']}/live/", {"live": True}, format="json")
    assert {e["name"]: e["live"] for e in BrowserClient().get(EVENTS).json()}["Later Cup"] is True
    # A Coast TT tournament in progress is live and links to its own page, not a submitted URL.
    venue = make_venue(staff, club, name="Hall")
    cup = make_tournament(
        staff, club, venue, name="Running Cup", starts_on=day(0), ends_on=day(1), timezone="Africa/Nairobi"
    )
    add_event(staff, cup)
    do(staff, cup, "publish")
    running = {e["name"]: e for e in BrowserClient().get(EVENTS).json()}["Running Cup"]
    assert (running["kind"], running["live"], running["live_url"]) == ("coast", True, "")


def test_a_reported_link_is_reported_once_per_person_and_curators_remove_it(staff, club, curator):
    made = submit(staff, club, starts_on=day(0), ends_on=day(0), live_url="https://kick.com/stream")
    curator.post(f"/api/v1/external-events/{made['id']}/approve/", {}, format="json")
    viewer = logged_in(make_user("viewer@example.com"))
    path = f"/api/v1/external-events/{made['id']}/report/"
    assert BrowserClient().post(path, {"reason": "broken"}, format="json").status_code in (401, 403)
    for _ in range(2):
        assert viewer.post(path, {"reason": "broken"}, format="json").status_code == 204
    assert LinkReport.objects.count() == 1
    queued = curator.get("/api/v1/external-events/review/").json()
    assert [(e["name"], e["report_count"]) for e in queued] == [("Nairobi Classic", 1)]
    removed = curator.post(f"/api/v1/external-events/{made['id']}/remove-link/", {}, format="json").json()
    assert removed["live_url"] == "" and removed["report_count"] == 0
    assert ExternalEvent.objects.get().live_url == ""


def test_filters_town_category_host_ours_past_and_month(staff, club, ours, theirs, curator):
    made = submit(staff, club)
    curator.post(f"/api/v1/external-events/{made['id']}/approve/", {}, format="json")
    old = submit(staff, club, name="Last Year Open", starts_on=day(-300), ends_on=day(-299))
    curator.post(f"/api/v1/external-events/{old['id']}/approve/", {}, format="json")
    public = BrowserClient()
    assert names(public, town="nairobi") == ["Last Year Open", "Nairobi Classic"]
    assert names(public, category="doubles") == ["Lake Open"]
    assert names(public, category="juniors") == ["Last Year Open", "Nairobi Classic"]
    assert names(public, host=str(club.id)) == ["Last Year Open", "Nairobi Classic", "Coast Open"]
    assert names(public, when="past") == ["Last Year Open"]
    assert "Last Year Open" not in names(public, when="upcoming")
    assert names(public, **{"from": day(15), "to": day(25)}) == ["Lake Open"]
    assert public.get(EVENTS, {"host": "nope"}).status_code == 400
    assert public.get(EVENTS, {"from": "13-2026"}).status_code == 400
    assert set(names(staff, ours="true")) == {"Coast Open", "Nairobi Classic", "Last Year Open"}
