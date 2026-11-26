"""Club staff add members directly; the person sets a password from a link (REQ-004, REQ-003)."""

import pytest
from django.core import mail

from accounts.models import User
from guests.models import Guest, GuestInvitation
from organizations.models import Membership

from .conftest import PASSWORD
from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db

ORGS = "/api/v1/organizations/"


def members(club) -> str:
    return f"{ORGS}{club.id}/members/"


def add(client, club, expect=201, **body) -> dict:
    response = client.post(members(club), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def token_of(link: str) -> str:
    return link.rstrip("/").rsplit("/", 1)[-1]


def test_a_new_person_is_a_member_at_once_and_sets_a_password_from_the_link(
    staff, club, client, django_capture_on_commit_callbacks
):
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        added = add(staff, club, display_name="Amina Said", email="Amina@Example.com")
    assert added["display_name"] == "Amina Said" and added["is_guest"] is True
    assert added["invite_link"] and "/join/" in added["invite_link"]
    assert [m.to for m in mail.outbox] == [["amina@example.com"]]
    assert "added you to" in mail.outbox[0].body and added["invite_link"] in mail.outbox[0].body
    listed = staff.get(members(club), {"search": "Amina"}).json()["results"]
    assert [(m["display_name"], m["is_guest"]) for m in listed] == [("Amina Said", True)]

    # Nobody can sign in as the new member until they set a password from the link.
    guest_user = User.objects.get(pk=added["user"])
    assert not guest_user.has_usable_password()

    token = token_of(added["invite_link"])
    shown = client.get(f"/api/v1/auth/invitations/{token}/").json()
    assert (shown["is_member"], shown["organization_name"], shown["entries"]) == (True, club.name, [])
    joined = client.post(
        f"/api/v1/auth/invitations/{token}/",
        {"display_name": "Amina Said", "email": "amina@example.com", "password": PASSWORD},
        format="json",
    )
    assert joined.status_code in (200, 201), joined.json()
    amina = User.objects.get(email="amina@example.com")
    assert amina.pk == guest_user.pk and amina.check_password(PASSWORD) and amina.is_email_verified
    membership = Membership.objects.get(organization=club, user=amina)
    assert membership.status == Membership.Status.ACTIVE
    listed = staff.get(members(club), {"search": "Amina"}).json()["results"]
    assert [m["is_guest"] for m in listed] == [False]
    # Single use.
    again = client.post(
        f"/api/v1/auth/invitations/{token}/",
        {"display_name": "X", "email": "x@example.com", "password": PASSWORD},
        format="json",
    )
    assert again.status_code in (404, 410)


def test_someone_already_registered_claims_the_membership_with_the_same_link(staff, club):
    brian = make_user("brian@example.com", display_name="Brian Otieno")
    added = add(staff, club, display_name="Brian", email="brian@example.com")
    player = logged_in(brian)
    link = f"/api/v1/auth/invitations/{token_of(added['invite_link'])}/claim/"
    claimed = player.post(link, {}, format="json")
    assert claimed.status_code == 200, claimed.json()
    assert Membership.objects.filter(organization=club, user=brian, status="active").exists()
    assert not Membership.objects.filter(organization=club, user_id=added["user"]).exists()


def test_the_reply_is_the_same_whether_or_not_the_address_is_registered(staff, club):
    make_user("known@example.com", display_name="Known")
    known = add(staff, club, display_name="Known", email="known@example.com")
    unknown = add(staff, club, display_name="Unknown", email="unknown@example.com")
    assert set(known) == set(unknown)
    assert (known["is_guest"], unknown["is_guest"]) == (True, True)
    assert not Membership.objects.filter(organization=club, user__email="known@example.com").exists()


def test_a_phone_only_add_gives_staff_the_link_and_sends_no_mail(staff, club):
    mail.outbox.clear()
    added = add(staff, club, display_name="Hassan", phone="+254712345678")
    assert added["invite_link"] and mail.outbox == []
    assert GuestInvitation.objects.get().phone == "+254712345678"


def test_only_members_staff_add_and_input_is_checked(staff, club):
    member = make_user("member@example.com")
    Membership.objects.create(organization=club, user=member)
    assert add(logged_in(member), club, expect=403, display_name="X", email="x@example.com")
    outsider = logged_in(make_user("outsider@example.com"))
    asked = outsider.post(members(club), {"display_name": "X", "email": "x@example.com"}, format="json")
    assert asked.status_code in (403, 404)
    assert "email" in add(staff, club, expect=400, display_name="No contact")["fields"]
    long_name = add(staff, club, expect=400, display_name="x" * 81, email="a@example.com")
    assert "display_name" in long_name["fields"]
    assert "email" in add(staff, club, expect=400, display_name="Bad", email="not-an-email")["fields"]
    assert not Guest.objects.exists()
