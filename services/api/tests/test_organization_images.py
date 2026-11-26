"""Pictures a club, team or facility shows of itself (REQ-058): who uploads, who sees, the limit, and what
is stored."""

from io import BytesIO

import pytest
from PIL import Image

from attachments.models import Attachment
from organizations import images
from organizations.models import Organization, OrganizationImage

from .conftest import BrowserClient
from .helpers import image_upload, logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db


def url(organization, image_id=""):
    return f"{ORGS}{organization.id}/images/" + (f"{image_id}/" if image_id else "")


def add(client, organization, **body):
    return client.post(url(organization), {"file": image_upload(), **body}, format="multipart")


@pytest.fixture
def admin(db):
    return make_user("admin@example.com", display_name="Admin")


@pytest.fixture(params=["club", "team", "facility"])
def organization(request, admin):
    made = logged_in(admin).post(
        ORGS, {"name": f"Coast {request.param}", "town": "Mombasa", "kind": request.param}, format="json"
    )
    assert made.status_code == 201, made.json()
    return Organization.objects.get(pk=made.json()["id"])


def test_admins_upload_pictures_that_any_signed_in_player_sees(organization, admin):
    staff = logged_in(admin)
    assert staff.get(url(organization)).json() == {"limit": 12, "images": []}
    big = image_upload(size=(3200, 1200), name="hall.jpg")
    added = staff.post(url(organization), {"file": big, "caption": "  Our hall  "}, format="multipart")
    assert added.status_code == 201, added.json()
    (picture,) = added.json()["images"]
    assert picture["caption"] == "Our hall"
    assert picture["file"]["url"].startswith(f"/api/v1/attachments/{picture['file']['id']}/content/")
    stored = Attachment.objects.get(pk=picture["file"]["id"])
    assert (stored.purpose, stored.content_type) == ("organization_image", "image/webp")
    with Image.open(BytesIO(stored.file.read())) as kept:
        assert kept.format == "WEBP" and max(kept.size) == images.IMAGE_SIDE

    # Somebody who isn't a member sees them, with a working link; signed out, nobody does.
    visitor = logged_in(make_user("visitor@example.com"))
    seen = visitor.get(url(organization)).json()["images"]
    assert [row["id"] for row in seen] == [picture["id"]]
    content = visitor.get(seen[0]["file"]["url"])
    assert content.status_code == 200 and content["Content-Type"] == "image/webp"
    assert visitor.get(f"/api/v1/attachments/{stored.id}/url/").status_code == 200
    assert BrowserClient().get(url(organization)).status_code == 401
    assert BrowserClient().get(f"/api/v1/attachments/{stored.id}/url/").status_code == 401

    # Only holders of roles.manage add or remove: not a visitor, not a plain member, not a captain.
    member = make_user("member@example.com")
    add_member(organization, member, "captain")
    for client in (visitor, logged_in(member)):
        assert add(client, organization).status_code == 403
        assert client.delete(url(organization, picture["id"])).status_code == 403
    assert OrganizationImage.objects.count() == 1

    removed = staff.delete(url(organization, picture["id"]))
    assert removed.status_code == 200 and removed.json()["images"] == []
    assert not Attachment.objects.filter(pk=stored.id).exists()
    # Once out of the gallery it is nobody's to read, the uploader's included.
    assert staff.get(f"/api/v1/attachments/{stored.id}/url/").status_code == 404


def test_uploads_are_checked_and_limited(admin, monkeypatch):
    made = logged_in(admin).post(ORGS, {"name": "Coast", "town": "Mombasa", "kind": "club"}, format="json")
    club = Organization.objects.get(pk=made.json()["id"])
    other = Organization.objects.create(name="Nyali", town="Mombasa")
    staff = logged_in(admin)
    assert staff.post(url(club), {"caption": "No file"}, format="multipart").status_code == 400
    text = BytesIO(b"<html>not a picture</html>")
    text.name = "hall.jpg"
    assert staff.post(url(club), {"file": text}, format="multipart").status_code == 400
    long = staff.post(url(club), {"file": image_upload(), "caption": "x" * 121}, format="multipart")
    assert long.status_code == 400 and set(long.json()["fields"]) == {"caption"}
    assert Attachment.objects.count() == 0

    monkeypatch.setattr(images, "MAX_IMAGES", 2)
    first = add(staff, club).json()["images"][0]
    assert add(staff, club).status_code == 201
    full = add(staff, club)
    assert full.status_code == 409 and full.json()["code"] == "image_limit"
    assert Attachment.objects.count() == 2  # the refused one left no file row behind

    # A picture is removed through its own organization only; another's id is not found.
    assert staff.delete(url(other, first["id"])).status_code == 403
    theirs = OrganizationImage.objects.create(
        organization=other,
        file=Attachment.store(
            owner=admin, purpose="organization_image", content=b"RIFF", content_type="image/webp"
        ),
    )
    assert staff.delete(url(club, theirs.id)).status_code == 404
    assert OrganizationImage.objects.filter(pk=theirs.id).exists()
