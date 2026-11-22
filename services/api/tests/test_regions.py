"""Regional bodies (REQ-048, EVAL-048): created by a platform super admin with its first admin (TASK-107),
the region's clubs, the yearly agenda, articles to clubs, meetings and sponsorships."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Country, Region
from organizations.models import Organization
from regions.models import Meeting

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, create_club
from .test_tournaments import add_event, do, make_tournament
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
ME = "/api/v1/me/"
BODIES = "/api/v1/regional-bodies/"


def soon(hours):
    return (timezone.now() + timedelta(hours=hours)).isoformat()


@pytest.fixture
def region():
    kenya = Country.objects.create(code="KE", name="Kenya", catalogue_only=True)
    return {
        "mombasa": Region.objects.create(country=kenya, name="Mombasa"),
        "kilifi": Region.objects.create(country=kenya, name="Kilifi"),
        "kenya": kenya,
    }


def placed(club, region_name="Mombasa"):
    club.country, club.region = "KE", region_name
    club.save(update_fields=["country", "region"])
    return club


@pytest.fixture
def world(region, admin, club):
    """Mombasa's body, created by a platform super admin and run by its official as admin; Coast TT Club
    (admin) in Mombasa with a member; Kilifi Spinners in Kilifi."""
    officer = make_user("officer@example.com", display_name="Officer Otieno")
    officer_client = logged_in(officer)
    root = logged_in(make_user("root@example.com", is_superuser=True, is_staff=True))
    made = root.post(
        BODIES,
        {"name": "Mombasa Region TT", "country": "KE", "region": "Mombasa", "admin_email": officer.email},
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = Organization.objects.get(pk=made.json()["id"])
    placed(club)
    member = make_user("member@example.com", display_name="Member Mwende")
    add_member(club, member)
    kilifi_admin = make_user("kilifi@example.com", display_name="Kilifi Admin")
    kilifi = placed(create_club(kilifi_admin, name="Kilifi Spinners"), "Kilifi")
    return {
        "body": body,
        "officer": officer_client,
        "root": root,
        "club": club,
        "admin": logged_in(admin),
        "member": logged_in(member),
        "kilifi": kilifi,
        "kilifi_admin": logged_in(kilifi_admin),
        "outsider": logged_in(make_user("outsider@example.com")),
    }


def org_url(org, path=""):
    return f"{ORGS}{org.id}/{path}"


def test_a_platform_super_admin_sets_up_the_body_once(world, region):
    body = world["body"]
    assert body.kind == "regional_body" and (body.country, body.region) == ("KE", "Mombasa")
    again = {"name": "Another", "country": "KE", "region": "Mombasa", "admin_email": "outsider@example.com"}
    assert world["root"].post(BODIES, again, format="json").status_code == 409
    # The body's own admin doesn't make bodies either: only the platform does.
    kilifi = {"name": "Mine", "country": "KE", "region": "Kilifi", "admin_email": "outsider@example.com"}
    assert world["officer"].post(BODIES, kilifi, format="json").status_code == 403
    assert world["outsider"].post(BODIES, kilifi, format="json").status_code == 403
    # Nobody picks the kind to make one.
    sneaky = world["outsider"].post(
        ORGS, {"name": "Fake body", "town": "Mombasa", "kind": "regional_body"}, format="json"
    )
    assert sneaky.status_code == 400
    assert [b["name"] for b in world["outsider"].get(BODIES).json()] == ["Mombasa Region TT"]


def test_the_body_sees_its_regions_clubs(world):
    clubs = world["officer"].get(org_url(world["body"], "region-clubs/"))
    assert clubs.status_code == 200
    assert [(c["name"], c["members"]) for c in clubs.json()] == [("Coast TT Club", 2)]
    assert world["member"].get(org_url(world["body"], "region-clubs/")).status_code == 403


def test_the_yearly_agenda_reaches_the_regions_clubs(world, staff):
    body = world["body"]
    venue = make_venue(staff, world["club"])
    cup = do(staff, add_event(staff, make_tournament(staff, world["club"], venue)), "publish")
    item = world["officer"].post(
        org_url(body, "agenda/"),
        {"kind": "tournament", "title": "Coast Open", "starts_on": "2026-12-05", "tournament_id": cup["id"]},
        format="json",
    )
    assert item.status_code == 201, item.json()
    assert item.json()["ends_on"] == "2026-12-05" and item.json()["tournament"]["name"] == "Coast Open"
    world["officer"].post(
        org_url(body, "agenda/"),
        {"kind": "meeting", "title": "AGM", "starts_on": "2027-03-01"},
        format="json",
    )

    seen = world["member"].get(org_url(body, "agenda/"), {"year": 2027}).json()
    assert [i["title"] for i in seen] == ["AGM"]
    assert [i["title"] for i in world["member"].get(f"{ME}agenda/").json()] == ["Coast Open", "AGM"]
    assert world["kilifi_admin"].get(org_url(body, "agenda/")).status_code == 403
    assert world["kilifi_admin"].get(f"{ME}agenda/").json() == []
    # Only the body's governance staff write it; a club admin of the region can't.
    assert (
        world["admin"]
        .post(org_url(body, "agenda/"), {"title": "Mine", "starts_on": "2027-01-01"}, format="json")
        .status_code
        == 403
    )


def test_articles_reach_the_clubs_they_are_for(world):
    body = world["body"]
    draft = (
        world["officer"]
        .post(
            org_url(body, "articles/"),
            {"title": "Season opens", "body": "Registration is open."},
            format="json",
        )
        .json()
    )
    assert draft["status"] == "draft"
    assert world["member"].get(f"{ME}articles/").json() == []
    assert world["member"].get(org_url(body, f"articles/{draft['id']}/")).status_code == 404

    published = world["officer"].post(org_url(body, f"articles/{draft['id']}/publish/"), format="json").json()
    assert published["status"] == "published" and published["published_at"]
    assert [a["title"] for a in world["member"].get(f"{ME}articles/").json()] == ["Season opens"]
    assert world["kilifi_admin"].get(f"{ME}articles/").json() == []

    # Chosen clubs only: a second Mombasa club doesn't get it.
    other = placed(create_club(make_user("nyali@example.com"), name="Nyali Loop"))
    nyali = logged_in(other.memberships.get().user)
    chosen = (
        world["officer"]
        .post(
            org_url(body, "articles/"),
            {"title": "Coast only", "body": "x", "audience": "chosen", "club_ids": [str(world["club"].id)]},
            format="json",
        )
        .json()
    )
    world["officer"].post(org_url(body, f"articles/{chosen['id']}/publish/"), format="json")
    assert {a["title"] for a in world["member"].get(f"{ME}articles/").json()} == {
        "Season opens",
        "Coast only",
    }
    assert [a["title"] for a in nyali.get(f"{ME}articles/").json()] == ["Season opens"]
    bad = world["officer"].post(
        org_url(body, "articles/"),
        {"title": "x", "body": "x", "club_ids": [str(world["kilifi"].id)]},
        format="json",
    )
    assert bad.status_code == 400


def test_a_body_meeting_invites_its_clubs_admins(world):
    body = world["body"]
    made = world["officer"].post(
        org_url(body, "meetings/"),
        {
            "title": "Clubs' meeting",
            "kind": "representatives",
            "starts_at": soon(2),
            "ends_at": soon(4),
            "audience": "club_admins",
            "agenda": [{"title": "Calendar for 2027"}, {"title": "Coast Open", "presenter": "Coast TT Club"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    meeting = made.json()
    path = org_url(body, f"meetings/{meeting['id']}/")
    assert world["admin"].get(path).status_code == 404  # a draft is for staff
    published = world["officer"].post(path + "publish/", format="json").json()
    assert [(i["display_name"], i["club"]) for i in published["invitees"]] == [
        ("Club Admin", "Coast TT Club")
    ]

    # The Coast admin is invited; a plain member and the Kilifi admin aren't.
    seen = world["admin"].get(path).json()
    assert seen["invitees"] == [] and seen["me"]["answer"] == "none"
    assert [m["title"] for m in world["admin"].get(f"{ME}meetings/").json()] == ["Clubs' meeting"]
    for outsider in (world["member"], world["kilifi_admin"]):
        assert outsider.get(path).status_code == 404
        assert outsider.post(path + "answer/", {"answer": "attending"}, format="json").status_code == 404

    assert (
        world["admin"].post(path + "answer/", {"answer": "apologies"}, format="json").json()["me"]["answer"]
        == "apologies"
    )
    assert world["admin"].post(path + "check-in/", format="json").status_code == 409  # not started
    assert (
        world["officer"].post(path + "minutes/", {"minutes": "Too early"}, format="json").status_code == 409
    )
    Meeting.objects.filter(pk=meeting["id"]).update(starts_at=timezone.now() - timedelta(minutes=5))
    checked = world["admin"].post(path + "check-in/", format="json").json()
    assert checked["me"]["checked_in_at"] and checked["me"]["answer"] == "attending"
    minutes = (
        world["officer"]
        .post(path + "minutes/", {"minutes": "Agreed the 2027 calendar."}, format="json")
        .json()
    )
    assert minutes["minutes"] == "Agreed the 2027 calendar."
    assert world["admin"].get(path).json()["minutes"] == "Agreed the 2027 calendar."


def test_a_club_meeting_stays_with_the_club(world, staff):
    made = staff.post(
        org_url(world["club"], "meetings/"),
        {"title": "Committee", "starts_at": soon(24), "ends_at": soon(26), "audience": "club_admins"},
        format="json",
    )
    assert made.status_code == 400  # only a body invites clubs' admins
    meeting = staff.post(
        org_url(world["club"], "meetings/"),
        {"title": "Members' meeting", "starts_at": soon(24), "ends_at": soon(26), "audience": "members"},
        format="json",
    ).json()
    staff.post(org_url(world["club"], f"meetings/{meeting['id']}/publish/"), format="json")
    # The region's official and body don't see the club's internal meetings.
    assert world["officer"].get(org_url(world["club"], f"meetings/{meeting['id']}/")).status_code == 404
    assert world["officer"].get(org_url(world["club"], "meetings/")).json() == []
    assert world["member"].get(org_url(world["club"], f"meetings/{meeting['id']}/")).status_code == 200
    cancelled = staff.post(
        org_url(world["club"], f"meetings/{meeting['id']}/cancel/"), {"reason": "Venue closed"}, format="json"
    )
    assert cancelled.json()["status"] == "cancelled"


def test_the_host_club_decides_a_sponsorship(world, staff):
    body = world["body"]
    venue = make_venue(staff, world["club"])
    draft = add_event(staff, make_tournament(staff, world["club"], venue))
    offer = {
        "tournament_id": draft["id"],
        "amount_minor": 5000000,
        "in_kind": [{"item": "Balls", "quantity": 72}],
    }
    assert (
        world["officer"].post(org_url(body, "sponsorships/"), offer, format="json").status_code == 400
    )  # a draft
    cup = do(staff, draft, "publish")
    made = world["officer"].post(
        org_url(body, "sponsorships/"), {**offer, "conditions": "Logo on the banner"}, format="json"
    )
    assert made.status_code == 201, made.json()
    sponsorship = made.json()
    assert world["officer"].post(org_url(body, "sponsorships/"), offer, format="json").status_code == 409
    assert (
        world["officer"]
        .post(org_url(body, "sponsorships/"), {"tournament_id": cup["id"]}, format="json")
        .status_code
        == 400
    )

    sponsors = f"/api/v1/tournaments/{cup['id']}/sponsors/"
    assert world["member"].get(sponsors).json() == []
    offers = f"/api/v1/tournaments/{cup['id']}/sponsorships/"
    assert world["member"].get(offers).status_code == 403
    assert [o["sponsor"]["name"] for o in staff.get(offers).json()] == ["Mombasa Region TT"]
    decide = f"{offers}{sponsorship['id']}/accept/"
    assert world["officer"].post(decide, format="json").status_code == 403  # the sponsor doesn't decide
    assert staff.post(decide, format="json").json()["status"] == "accepted"
    shown = world["outsider"].get(sponsors).json()
    assert shown == [
        {
            "id": sponsorship["id"],
            "sponsor": {"id": str(body.id), "name": "Mombasa Region TT", "town": "Mombasa"},
            "amount_minor": 5000000,
            "currency": "KES",
            "in_kind": [{"item": "Balls", "quantity": 72}],
        }
    ]
    assert staff.post(decide, format="json").status_code == 409
    withdrawn = world["officer"].post(
        org_url(body, f"sponsorships/{sponsorship['id']}/withdraw/"), {"reason": "Budget cut"}, format="json"
    )
    assert withdrawn.json()["status"] == "withdrawn"
    assert world["outsider"].get(sponsors).json() == []
