"""Private attachments, signed links and the profile picture (REQ-020, REQ-032, REQ-006; TASK-016)."""

import struct
from io import BytesIO

import pytest
from django.core import signing
from django.core.files.storage import storages
from PIL import Image

from attachments.models import Attachment
from profiles.models import PlayerProfile, profile_for

from .conftest import BrowserClient
from .helpers import image_upload, logged_in, make_user

pytestmark = pytest.mark.django_db
AVATAR = "/api/v1/me/avatar/"
PROFILE = "/api/v1/me/profile/"


def upload(client, file):
    return client.put(AVATAR, {"file": file}, format="multipart")


def link_url(attachment_id) -> str:
    return f"/api/v1/attachments/{attachment_id}/url/"


@pytest.fixture
def ama(db):
    return make_user("ama@example.com", display_name="Ama Wanjiru")


@pytest.fixture
def baraka(db):
    return make_user("baraka@example.com", display_name="Baraka Otieno")


def later(monkeypatch, seconds):
    """Move the signer's clock forward."""
    import time

    now = time.time()
    monkeypatch.setattr("django.core.signing.time.time", lambda: now + seconds)


# --- upload validation -------------------------------------------------------------------------------


def test_upload_stores_a_normalized_private_image(ama):
    client = logged_in(ama)
    response = upload(client, image_upload())
    assert response.status_code == 200, response.json()
    avatar = response.json()["avatar"]
    assert set(avatar) == {"id", "url", "expires_at"}

    attachment = Attachment.objects.get(pk=avatar["id"])
    assert (attachment.owner, attachment.purpose, attachment.content_type) == (ama, "avatar", "image/webp")
    assert attachment.file.name == f"avatar/{attachment.id}.webp"  # never the uploader's file name
    with Image.open(attachment.file) as stored:
        assert stored.format == "WEBP"
        assert max(stored.size) == 512
    assert attachment.size == attachment.file.size
    assert len(attachment.sha256) == 64

    content = BrowserClient().get(avatar["url"])  # no session: the signature is the authorization
    assert content.status_code == 200
    assert content["Content-Type"] == "image/webp"
    assert content["Cache-Control"] == "private, no-store"
    assert content["X-Content-Type-Options"] == "nosniff"
    assert b"".join(content.streaming_content) == attachment.file.open().read()


def test_upload_drops_photo_location_metadata(ama):
    exif = Image.Exif()
    exif[0x010F] = "MARKER-CAMERA-MAKE"
    exif[0x8825] = {1: "S", 2: (4.0, 3.0, 0.0), 3: "E", 4: (39.0, 40.0, 0.0)}  # GPS position
    response = upload(logged_in(ama), image_upload(exif=exif))
    assert response.status_code == 200
    attachment = Attachment.objects.get()
    with Image.open(attachment.file) as stored:
        assert not stored.getexif()
    assert b"MARKER-CAMERA-MAKE" not in attachment.file.open().read()


@pytest.mark.parametrize(
    "make",
    [
        lambda: image_upload("GIF", name="me.gif"),
        lambda: image_upload("BMP", name="me.jpg"),  # the name doesn't decide the type
        lambda: BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"),
        lambda: BytesIO(b"\xff\xd8\xff\xe0 not really a jpeg"),
        lambda: BytesIO(b"x" * (5 * 1024 * 1024 + 1)),
    ],
    ids=["gif", "bmp-named-jpg", "svg", "broken-jpeg", "over-5-mb"],
)
def test_upload_rejects_other_files(ama, make):
    file = make()
    file.name = getattr(file, "name", "upload.jpg")
    response = upload(logged_in(ama), file)
    assert response.status_code == 400, response.content
    assert "file" in response.json()["fields"]
    assert not Attachment.objects.exists()


def test_damaged_images_are_a_400_not_a_crash(ama):
    """Pillow raises all sorts of errors on damaged files; each must come back as a `file` message."""
    good = image_upload("PNG", name="me.png").getvalue()
    damaged = [
        good.replace(b"IDAT", b"ID~T"),  # broken chunk name
        good[: len(good) // 2],  # truncated
        good[:20] + bytes(40) + good[60:],  # header overwritten
    ]
    client = logged_in(ama)
    for content in damaged:
        file = BytesIO(content)
        file.name = "me.png"
        response = upload(client, file)
        assert response.status_code == 400, response.content
        assert "file" in response.json()["fields"]
    assert not Attachment.objects.exists()


@pytest.mark.parametrize("error", [SyntaxError("broken PNG file"), struct.error("bad"), MemoryError()])
def test_any_decoder_failure_is_a_400(ama, monkeypatch, error):
    def explode(*args, **kwargs):
        raise error

    monkeypatch.setattr("attachments.images.ImageOps.exif_transpose", explode)
    response = upload(logged_in(ama), image_upload())
    assert response.status_code == 400
    assert response.json()["fields"] == {"file": "Choose a JPEG, PNG or WebP image."}


def test_oversized_body_is_refused_before_it_is_read(ama):
    response = logged_in(ama).put(
        AVATAR, {"file": image_upload()}, format="multipart", CONTENT_LENGTH=6 * 1024 * 1024
    )
    assert response.status_code == 400
    assert "file" in response.json()["fields"]


def test_a_failed_save_leaves_no_file_behind(ama, monkeypatch):
    client = logged_in(ama)
    client.raise_request_exception = False

    def fail(self, *args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(PlayerProfile, "save", fail)
    assert upload(client, image_upload()).status_code == 500
    assert not Attachment.objects.exists()
    storage = storages["attachments"]
    assert not storage.exists("avatar") or storage.listdir("avatar")[1] == []


def test_upload_rejects_images_with_too_many_pixels(ama, monkeypatch):
    monkeypatch.setattr("attachments.images.MAX_PIXELS", 100 * 100)
    assert upload(logged_in(ama), image_upload(size=(101, 100))).status_code == 400
    assert upload(logged_in(ama), image_upload(size=(100, 100))).status_code == 200


def test_upload_needs_a_file_and_a_login(ama):
    assert upload(BrowserClient(), image_upload()).status_code == 401
    client = logged_in(ama)
    assert client.put(AVATAR, {}, format="multipart").status_code == 400
    assert client.put(AVATAR, {"file": "text"}, format="json").status_code == 415


def test_profile_patch_cannot_point_the_avatar_at_another_attachment(ama, baraka):
    upload(logged_in(baraka), image_upload())
    theirs = Attachment.objects.get()
    response = logged_in(ama).patch(PROFILE, {"avatar": str(theirs.id), "nickname": "A"}, format="json")
    assert response.status_code == 200
    assert response.json()["avatar"] is None
    assert profile_for(ama).avatar is None


@pytest.fixture
def commits(django_capture_on_commit_callbacks):
    """Stored files are removed when the deleting transaction commits; run those callbacks in tests."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


def test_replacing_and_removing_delete_the_old_file(ama, commits):
    client = logged_in(ama)
    first = upload(client, image_upload()).json()["avatar"]
    first_name = Attachment.objects.get(pk=first["id"]).file.name
    storage = storages["attachments"]
    assert storage.exists(first_name)

    with commits():
        second = upload(client, image_upload("PNG", name="me.png")).json()["avatar"]
    assert second["id"] != first["id"]
    assert list(Attachment.objects.values_list("id", flat=True)) == [profile_for(ama).avatar_id]
    assert not storage.exists(first_name)
    assert BrowserClient().get(first["url"]).status_code == 404  # an unexpired link to a deleted file

    with commits():
        assert client.delete(AVATAR).status_code == 204
    assert client.get(PROFILE).json()["avatar"] is None
    assert not Attachment.objects.exists()
    assert storage.listdir("avatar")[1] == []
    assert client.delete(AVATAR).status_code == 204  # nothing to remove is fine


def test_deleting_the_account_removes_the_file(ama, commits):
    upload(logged_in(ama), image_upload())
    name = Attachment.objects.get().file.name
    with commits():
        ama.delete()
    assert not storages["attachments"].exists(name)


# --- signed links ------------------------------------------------------------------------------------


def test_link_expires(ama, monkeypatch, settings):
    avatar = upload(logged_in(ama), image_upload()).json()["avatar"]
    later(monkeypatch, settings.ATTACHMENT_URL_TTL - 5)
    assert BrowserClient().get(avatar["url"]).status_code == 200
    later(monkeypatch, settings.ATTACHMENT_URL_TTL + 5)
    response = BrowserClient().get(avatar["url"])
    assert response.status_code == 403
    assert response.json()["code"] == "link_expired"


def test_link_is_bound_to_its_attachment_and_signature(ama, baraka):
    mine = upload(logged_in(ama), image_upload()).json()["avatar"]
    theirs = upload(logged_in(baraka), image_upload()).json()["avatar"]
    token = mine["url"].split("token=")[1]
    anonymous = BrowserClient()

    assert anonymous.get(theirs["url"].split("?")[0], {"token": token}).status_code == 403
    assert anonymous.get(mine["url"].split("?")[0]).status_code == 403
    assert anonymous.get(mine["url"].split("?")[0], {"token": token[:-2] + "xx"}).status_code == 403
    # A value signed with the same key for another purpose is not a link.
    forged = signing.dumps(mine["id"], salt="something.else")
    assert anonymous.get(mine["url"].split("?")[0], {"token": forged}).status_code == 403
    assert anonymous.get(mine["url"]).status_code == 200


def test_who_can_get_a_link(ama, baraka):
    """Owner always; other signed-in players only while the owner is listed; nobody when signed out."""
    avatar = upload(logged_in(ama), image_upload()).json()["avatar"]
    url = link_url(avatar["id"])
    other = logged_in(baraka)

    assert logged_in(ama).get(url).status_code == 200
    assert BrowserClient().get(url).status_code == 401
    assert other.get(url).status_code == 404  # not listed: indistinguishable from a missing attachment
    assert other.get(link_url("00000000-0000-4000-8000-000000000000")).status_code == 404

    PlayerProfile.objects.filter(user=ama).update(directory_opt_in=True)
    issued = other.get(url)
    assert issued.status_code == 200
    assert BrowserClient().get(issued.json()["url"]).status_code == 200


def test_losing_access_blocks_new_links(ama, baraka):
    PlayerProfile.objects.update_or_create(user=ama, defaults={"directory_opt_in": True})
    avatar = upload(logged_in(ama), image_upload()).json()["avatar"]
    url = link_url(avatar["id"])
    other = logged_in(baraka)
    assert other.get(url).status_code == 200

    # The owner opts out of the directory: other players get no new link.
    logged_in(ama).patch(PROFILE, {"directory_opt_in": False}, format="json")
    assert other.get(url).status_code == 404

    # A deactivated account gets no new link either, even to a listed player's picture.
    logged_in(ama).patch(PROFILE, {"directory_opt_in": True}, format="json")
    assert other.get(url).status_code == 200
    baraka.is_active = False
    baraka.save()
    assert other.get(url).status_code == 401

    # A deactivated owner's picture is no longer available to others.
    carol = logged_in(make_user("carol@example.com"))
    assert carol.get(url).status_code == 200
    ama.is_active = False
    ama.save()
    assert carol.get(url).status_code == 404


def test_a_replaced_avatar_is_not_reachable_through_the_old_id(ama, baraka):
    PlayerProfile.objects.update_or_create(user=ama, defaults={"directory_opt_in": True})
    client = logged_in(ama)
    old = upload(client, image_upload()).json()["avatar"]
    upload(client, image_upload())
    assert logged_in(baraka).get(link_url(old["id"])).status_code == 404


# --- where avatars appear ----------------------------------------------------------------------------


def test_directory_and_player_page_carry_a_working_link_for_listed_players(ama, baraka):
    PlayerProfile.objects.update_or_create(user=ama, defaults={"directory_opt_in": True})
    upload(logged_in(ama), image_upload())
    viewer = logged_in(baraka)

    card = viewer.get("/api/v1/players/?search=ama").json()["results"][0]
    page = viewer.get(f"/api/v1/players/{ama.id}/").json()
    for avatar in (card["avatar"], page["avatar"]):
        assert avatar["id"] == str(profile_for(ama).avatar_id)
        assert BrowserClient().get(avatar["url"]).status_code == 200

    profile_for(baraka)
    PlayerProfile.objects.filter(user=baraka).update(directory_opt_in=True)
    assert viewer.get(f"/api/v1/players/{baraka.id}/").json()["avatar"] is None  # no picture yet
