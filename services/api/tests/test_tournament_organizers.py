"""Who organizes a tournament, coaches organizing as themselves or their firm, officials overseeing their
region's tournaments, and a tournament's cover picture and documents (REQ-007, REQ-047, REQ-048;
TASK-117)."""

import pytest

from attachments.models import Attachment
from organizations.models import Membership, Organization

from .helpers import image_upload, logged_in, make_user
from .test_authority import kenya, official  # noqa: F401  (fixture)
from .test_coaching import ME, become_coach
from .test_roles import ORGS
from .test_tournaments import TOURNAMENTS, add_event, do, make_tournament
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
OVERSEEN = f"{TOURNAMENTS}overseen/"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def pdf_upload(content=PDF, name="prospectus.pdf"):
    from io import BytesIO

    out = BytesIO(content)
    out.name = name
    return out


@pytest.fixture
def coach_client(db):
    client = logged_in(make_user("coach@example.com", display_name="Juma Coach"))
    become_coach(client, firm_name="  Coast Spin Academy  ")
    return client


def open_desk(client, presented_as="coach"):
    response = client.post(f"{ME}coach-profile/organizer/", {"presented_as": presented_as}, format="json")
    assert response.status_code == 200, response.json()
    return Organization.objects.get(pk=response.json()["organization_id"])


def test_a_club_tournament_names_the_club_as_organizer(staff, club):
    tournament = make_tournament(staff, club)
    assert tournament["organizer"] == {"name": club.name, "kind": club.kind, "label": "Club"}
    assert tournament["presented_as"] == ""
    refused = staff.patch(f"{TOURNAMENTS}{tournament['id']}/", {"presented_as": "coach"}, format="json")
    assert refused.status_code == 400 and "presented_as" in refused.json()["fields"]


def test_a_regional_body_tournament_names_the_body(kenya):  # noqa: F811
    region = kenya["mombasa"]
    officer = official("officer@example.com", kenya, region)
    made = officer.post(
        "/api/v1/regional-bodies/",
        {"name": "Coast Table Tennis Committee", "region_id": region.id},
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = Organization.objects.get(pk=made.json()["id"])
    tournament = make_tournament(officer, body)
    assert tournament["organizer"] == {
        "name": "Coast Table Tennis Committee",
        "kind": "regional_body",
        "label": "Regional body",
    }


def test_a_coach_organizes_as_themselves_or_their_firm(coach_client):
    profile = coach_client.get(f"{ME}coach-profile/").json()
    assert profile["firm_name"] == "Coast Spin Academy" and profile["organizer_id"] is None

    desk = open_desk(coach_client)
    assert desk.kind == "coaching" and desk.name == "Juma Coach"
    assert Membership.objects.get(organization=desk).user.email == "coach@example.com"
    # Opening it again reuses the same desk, renamed for the firm.
    assert open_desk(coach_client, "firm").pk == desk.pk
    desk.refresh_from_db()
    assert desk.name == "Coast Spin Academy"
    assert coach_client.get(f"{ME}coach-profile/").json()["organizer_id"] == str(desk.id)

    as_coach = make_tournament(coach_client, desk)
    assert as_coach["presented_as"] == "coach"
    assert as_coach["organizer"] == {"name": "Juma Coach", "kind": "coach", "label": "Coach"}
    as_firm = make_tournament(coach_client, desk, presented_as="firm")
    assert as_firm["organizer"] == {"name": "Coast Spin Academy", "kind": "firm", "label": "Coaching firm"}


def test_organizing_as_a_firm_needs_its_name(db):
    client = logged_in(make_user("solo@example.com", display_name="Solo"))
    refused = client.post(f"{ME}coach-profile/organizer/", {}, format="json")
    assert refused.status_code == 404  # not a coach yet
    become_coach(client)
    refused = client.post(f"{ME}coach-profile/organizer/", {"presented_as": "firm"}, format="json")
    assert refused.status_code == 400 and refused.json()["code"] == "no_firm"
    desk = open_desk(client)
    refused = client.post(
        f"{ORGS}{desk.id}/tournaments/",
        {"name": "Open", "starts_on": "2026-12-05", "ends_on": "2026-12-05", "presented_as": "firm"},
        format="json",
    )
    assert refused.status_code == 400 and "presented_as" in refused.json()["fields"]


def test_a_coach_desk_stays_out_of_the_club_directory_and_cannot_be_registered(coach_client, club):
    desk = open_desk(coach_client)
    listed = [row["id"] for row in coach_client.get(ORGS).json()["results"]]
    assert str(club.id) in listed and str(desk.id) not in listed
    asked = coach_client.get(ORGS, {"kind": "coaching"}).json()["results"]
    assert [row["id"] for row in asked] == [str(desk.id)]
    refused = coach_client.post(ORGS, {"name": "Fake", "town": "Mombasa", "kind": "coaching"}, format="json")
    assert refused.status_code == 400


def test_officials_oversee_published_tournaments_in_their_region(staff, club, kenya):  # noqa: F811
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    venue = make_venue(staff, club)
    out = add_event(staff, make_tournament(staff, club, venue, name="Coast Open"))
    do(staff, out, "publish")
    make_tournament(staff, club, venue, name="Still a draft")

    mombasa = official("mombasa@example.com", kenya, kenya["mombasa"])
    seen = mombasa.get(OVERSEEN).json()["results"]
    assert [row["name"] for row in seen] == ["Coast Open"]
    assert seen[0]["organizer"]["name"] == club.name
    assert mombasa.get(OVERSEEN, {"when": "past"}).json()["results"] == []

    kilifi = official("kilifi@example.com", kenya, kenya["kilifi"])
    assert kilifi.get(OVERSEEN).json()["results"] == []
    country = official("country@example.com", kenya)
    assert [row["name"] for row in country.get(OVERSEEN).json()["results"]] == ["Coast Open"]
    player = logged_in(make_user("player@example.com"))
    assert player.get(OVERSEEN).json()["results"] == []

    # A regional body's members oversee their region too, even without an appointment.
    made = mombasa.post(
        "/api/v1/regional-bodies/",
        {"name": "Coast TT Committee", "region_id": kenya["mombasa"].id},
        format="json",
    )
    body = Organization.objects.get(pk=made.json()["id"])
    secretary = make_user("secretary@example.com")
    Membership.objects.create(organization=body, user=secretary)
    assert [row["name"] for row in logged_in(secretary).get(OVERSEEN).json()["results"]] == ["Coast Open"]


def test_staff_set_a_cover_and_documents_that_viewers_open(staff, club):
    venue = make_venue(staff, club)
    tournament = add_event(staff, make_tournament(staff, club, venue))
    cover_url = f"{TOURNAMENTS}{tournament['id']}/cover/"
    docs_url = f"{TOURNAMENTS}{tournament['id']}/documents/"

    with_cover = staff.put(cover_url, {"file": image_upload(name="poster.jpg")}, format="multipart")
    assert with_cover.status_code == 200, with_cover.json()
    cover = with_cover.json()["cover"]
    assert cover["url"].startswith(f"/api/v1/attachments/{cover['id']}/content/")
    first = cover["id"]
    replaced = staff.put(cover_url, {"file": image_upload(name="poster2.png", fmt="PNG")}, format="multipart")
    assert replaced.json()["cover"]["id"] != first
    assert not Attachment.objects.filter(pk=first).exists()

    added = staff.post(docs_url, {"title": "Prospectus", "file": pdf_upload()}, format="multipart")
    assert added.status_code == 201, added.json()
    (document,) = added.json()["documents"]
    assert document["title"] == "Prospectus"
    not_pdf = staff.post(
        docs_url, {"title": "Rules", "file": pdf_upload(b"<html>hi</html>", "rules.pdf")}, format="multipart"
    )
    assert not_pdf.status_code == 400

    # A player sees neither while it is a draft, and both once it is published.
    player = logged_in(make_user("player@example.com"))
    assert player.get(f"/api/v1/attachments/{document['file']['id']}/url/").status_code == 404
    do(staff, tournament, "publish")
    shown = player.get(f"{TOURNAMENTS}{tournament['id']}/").json()
    assert shown["cover"]["id"] == replaced.json()["cover"]["id"]
    link = player.get(f"/api/v1/attachments/{document['file']['id']}/url/")
    assert link.status_code == 200
    content = player.get(link.json()["url"])
    assert content.status_code == 200 and content["Content-Type"] == "application/pdf"
    assert content["Content-Disposition"].startswith("attachment;")
    assert b"".join(content.streaming_content) == PDF

    # Only the host's staff change them.
    refused = player.post(docs_url, {"title": "Mine", "file": pdf_upload()}, format="multipart")
    assert refused.status_code == 403
    removed = staff.delete(f"{docs_url}{document['id']}/")
    assert removed.status_code == 200 and removed.json()["documents"] == []
    assert not Attachment.objects.filter(pk=document["file"]["id"]).exists()
    cleared = staff.delete(cover_url)
    assert cleared.status_code == 200 and cleared.json()["cover"] is None
