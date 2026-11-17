"""Custom member fields and field access rules (REQ-005, EVAL-005, TASK-014)."""

import pytest

from organizations.member_fields import MAX_ACTIVE_FIELDS
from organizations.models import MemberField, MemberFieldValue

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, code, create_club

pytestmark = pytest.mark.django_db
MEMBERSHIPS = "/api/v1/me/memberships/"
SECRET = "Owes two months of dues"


def fields_url(org, field=None, action=""):
    return f"{ORGS}{org.id}/member-fields/" + (f"{field['id']}/{action}" if field else "")


def member_values_url(org, membership):
    return f"{ORGS}{org.id}/members/{membership.id}/fields/"


def my_values_url(membership):
    return f"{MEMBERSHIPS}{membership.id}/fields/"


def values(response) -> dict:
    assert response.status_code == 200, response.json()
    return {entry["field"]["label"]: entry["value"] for entry in response.json()}


@pytest.fixture
def admin(db):
    return make_user("admin@example.com", display_name="Club Admin")


@pytest.fixture
def club(admin):
    return create_club(admin)


@pytest.fixture
def staff(admin):
    return logged_in(admin)


@pytest.fixture
def member(club):
    return add_member(club, make_user("juma@example.com", display_name="Juma"))


def make_field(staff, club, label, kind="text", **extra) -> dict:
    response = staff.post(fields_url(club), {"label": label, "kind": kind, **extra}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.fixture
def shirt(staff, club):
    return make_field(
        staff, club, "Shirt size", "choice", options=["S", "M", "L"], visibility="member", required=True
    )


@pytest.fixture
def notes(staff, club):
    return make_field(staff, club, "Committee notes")  # staff-only unless said otherwise


def test_staff_define_every_kind_of_field(staff, club):
    make_field(staff, club, "Membership number", "text", visibility="member")
    make_field(staff, club, "Locker", "number")
    make_field(staff, club, "Joined federation", "date")
    make_field(staff, club, "Has own bat", "boolean", visibility="member")
    make_field(staff, club, "Shirt size", "choice", options=["S", " M ", "m", "L"], required=True)

    listed = {f["label"]: f for f in staff.get(fields_url(club)).json()}
    assert [f["kind"] for f in listed.values()] == ["text", "number", "date", "boolean", "choice"]
    assert listed["Shirt size"]["options"] == ["S", "M", "L"]  # trimmed, duplicates by case dropped
    assert listed["Shirt size"]["required"] and listed["Locker"]["visibility"] == "staff"


def test_field_definitions_are_validated(staff, club, shirt):
    def create(**body):
        return staff.post(fields_url(club), body, format="json")

    assert set(create(label="Level", kind="choice", options=["Only one"]).json()["fields"]) == {"options"}
    assert set(create(label="Level", kind="choice").json()["fields"]) == {"options"}
    assert set(create(label="Age", kind="number", options=["1", "2"]).json()["fields"]) == {"options"}
    assert set(create(label="shirt SIZE", kind="text").json()["fields"]) == {"label"}  # same label
    assert set(create(label="Height", kind="ruler").json()["fields"]) == {"kind"}

    # The type is fixed once values may exist; everything else can change.
    retype = staff.patch(fields_url(club, shirt), {"kind": "text"}, format="json")
    assert retype.status_code == 400 and set(retype.json()["fields"]) == {"kind"}
    changed = staff.patch(
        fields_url(club, shirt), {"label": "T-shirt", "options": ["S", "M", "L", "XL"]}, format="json"
    )
    assert changed.status_code == 200 and changed.json()["options"][-1] == "XL"
    assert changed.json()["required"] is True  # untouched


def test_only_member_managers_change_field_definitions(club, staff, member, shirt, notes):
    plain = logged_in(member.user)
    roles_only = club.roles.create(name="Role keeper", permissions=["roles.manage"])
    keeper = logged_in(add_member(club, make_user("keeper@example.com"), roles_only).user)
    outsider = logged_in(make_user("outsider@example.com"))

    for client in (plain, keeper, outsider):
        assert code(client.post(fields_url(club), {"label": "X", "kind": "text"}, format="json")) == (
            "permission_denied"
        )
        assert client.patch(fields_url(club, notes), {"label": "X"}, format="json").status_code == 403
        assert client.post(fields_url(club, notes, "retire/")).status_code == 403
        assert client.post(fields_url(club, notes, "restore/")).status_code == 403
    assert MemberField.objects.get(pk=notes["id"]).label == "Committee notes"

    # Members learn only of the fields they may fill in; the staff-only field isn't even named.
    assert [f["label"] for f in plain.get(fields_url(club)).json()] == ["Shirt size"]
    assert [f["label"] for f in keeper.get(fields_url(club)).json()] == ["Shirt size"]
    assert outsider.get(fields_url(club)).status_code == 403
    assert len(staff.get(fields_url(club)).json()) == 2


def test_staff_only_values_never_reach_the_member(club, staff, member, shirt, notes):
    saved = staff.patch(
        member_values_url(club, member), {"values": {shirt["id"]: "M", notes["id"]: SECRET}}, format="json"
    )
    assert values(saved) == {"Shirt size": "M", "Committee notes": SECRET}
    assert values(staff.get(member_values_url(club, member))) == {
        "Shirt size": "M",
        "Committee notes": SECRET,
    }

    plain = logged_in(member.user)
    mine = plain.get(my_values_url(member))
    assert values(mine) == {"Shirt size": "M"}
    assert SECRET not in mine.text and "Committee notes" not in mine.text
    assert SECRET not in plain.get(MEMBERSHIPS).text

    # Knowing the staff-only field's id doesn't help: it is as unknown as a made-up one.
    for field_id in (notes["id"], "00000000-0000-0000-0000-000000000000"):
        sneaky = plain.patch(my_values_url(member), {"values": {field_id: "cleared"}}, format="json")
        assert sneaky.status_code == 400 and sneaky.json()["fields"] == {
            "values": "One or more fields don't exist here."
        }
    assert MemberFieldValue.objects.get(field_id=notes["id"]).value == SECRET

    # The staff view of a member is for members.manage only.
    assert plain.get(member_values_url(club, member)).status_code == 403
    roles_only = club.roles.create(name="Role keeper", permissions=["roles.manage"])
    keeper = logged_in(add_member(club, make_user("keeper@example.com"), roles_only).user)
    assert keeper.get(member_values_url(club, member)).status_code == 403
    assert keeper.patch(member_values_url(club, member), {"values": {}}, format="json").status_code == 403


def test_members_fill_in_only_their_own_member_visible_fields(club, staff, member, shirt):
    other = add_member(club, make_user("zawadi@example.com"))
    plain = logged_in(member.user)

    assert values(plain.get(my_values_url(member))) == {"Shirt size": None}
    assert values(plain.patch(my_values_url(member), {"values": {shirt["id"]: "L"}}, format="json")) == {
        "Shirt size": "L"
    }
    assert values(staff.get(member_values_url(club, member))) == {"Shirt size": "L"}

    # Someone else's membership isn't theirs to read or write.
    assert plain.get(my_values_url(other)).status_code == 404
    assert plain.patch(my_values_url(other), {"values": {shirt["id"]: "S"}}, format="json").status_code == 404
    assert not MemberFieldValue.objects.filter(membership=other).exists()

    # Making the field staff-only takes it away from the member, value included.
    staff.patch(fields_url(club, shirt), {"visibility": "staff"}, format="json")
    assert values(plain.get(my_values_url(member))) == {}
    assert (
        plain.patch(my_values_url(member), {"values": {shirt["id"]: "S"}}, format="json").status_code == 400
    )
    assert values(staff.get(member_values_url(club, member))) == {"Shirt size": "L"}


def test_values_are_checked_against_the_field_type(club, staff, member):
    text = make_field(staff, club, "Nickname")
    number = make_field(staff, club, "Locker", "number")
    day = make_field(staff, club, "Medical expires", "date")
    flag = make_field(staff, club, "Has own bat", "boolean", required=True)
    choice = make_field(staff, club, "Level", "choice", options=["Beginner", "Advanced"])
    url = member_values_url(club, member)

    def rejected(field, value) -> bool:
        response = staff.patch(url, {"values": {field["id"]: value}}, format="json")
        return response.status_code == 400 and set(response.json()["fields"]) == {field["id"]}

    assert rejected(text, 12) and rejected(text, "x" * 501) and rejected(text, ["a"])
    assert rejected(number, "12") and rejected(number, True) and rejected(number, 10**13)
    assert rejected(day, "31/12/2026") and rejected(day, "2026-02-30") and rejected(day, 20261231)
    assert rejected(flag, "yes") and rejected(flag, 1)
    assert rejected(flag, None)  # required: can't be cleared
    assert rejected(choice, "Expert") and rejected(choice, {"a": 1})
    assert not MemberFieldValue.objects.exists()

    good = {
        text["id"]: "  Smasher ",
        number["id"]: 14,
        day["id"]: "2027-03-31",
        flag["id"]: False,
        choice["id"]: "Advanced",
    }
    assert values(staff.patch(url, {"values": good}, format="json")) == {
        "Nickname": "Smasher",
        "Locker": 14,
        "Medical expires": "2027-03-31",
        "Has own bat": False,  # "no" is an answer, not a blank
        "Level": "Advanced",
    }

    # One bad value saves nothing; fields left out keep their value; blank clears an optional field.
    mixed = staff.patch(url, {"values": {number["id"]: 20, choice["id"]: "Expert"}}, format="json")
    assert mixed.status_code == 400
    cleared = values(staff.patch(url, {"values": {text["id"]: " ", choice["id"]: None}}, format="json"))
    assert cleared["Nickname"] is None and cleared["Level"] is None and cleared["Locker"] == 14
    assert MemberFieldValue.objects.count() == 3


def test_retiring_a_field_hides_it_and_keeps_its_values(club, staff, member, shirt):
    plain = logged_in(member.user)
    plain.patch(my_values_url(member), {"values": {shirt["id"]: "M"}}, format="json")

    retired = staff.post(fields_url(club, shirt, "retire/"))
    assert retired.status_code == 200 and retired.json()["retired_at"]
    assert staff.post(fields_url(club, shirt, "retire/")).status_code == 200  # repeat is harmless

    assert plain.get(fields_url(club)).json() == []
    assert values(plain.get(my_values_url(member))) == {}
    assert values(staff.get(member_values_url(club, member))) == {}
    for client, url in ((plain, my_values_url(member)), (staff, member_values_url(club, member))):
        assert client.patch(url, {"values": {shirt["id"]: "L"}}, format="json").status_code == 400
    assert code(staff.patch(fields_url(club, shirt), {"label": "Shirt"}, format="json")) == "field_retired"
    assert MemberFieldValue.objects.get(field_id=shirt["id"]).value == "M"  # history preserved

    # Staff still see the retired definition, and its label is free for a new field.
    assert [f["retired_at"] is not None for f in staff.get(fields_url(club)).json()] == [True]
    replacement = make_field(staff, club, "Shirt size", "text")
    assert code(staff.post(fields_url(club, shirt, "restore/"))) == "label_taken"
    staff.patch(fields_url(club, replacement), {"label": "Shirt size (old)"}, format="json")

    restored = staff.post(fields_url(club, shirt, "restore/"))
    assert restored.status_code == 200 and restored.json()["retired_at"] is None
    assert values(plain.get(my_values_url(member))) == {"Shirt size": "M"}


def test_fields_and_values_stay_inside_their_organization(admin, club, staff, member, shirt, notes):
    owner = make_user("rival@example.com")
    rival = create_club(owner, "Nyali TT Club")
    rival_staff = logged_in(owner)
    rival_field = make_field(rival_staff, rival, "Shirt size", visibility="member")  # same label is fine
    rival_member = add_member(rival, make_user("pendo@example.com"))

    # Another organization's staff can't see or touch this club's fields, members or values.
    assert rival_staff.get(fields_url(club)).status_code == 403
    assert rival_staff.patch(fields_url(club, shirt), {"label": "X"}, format="json").status_code == 403
    assert rival_staff.get(member_values_url(club, member)).status_code == 403
    # Mixing ids across organizations finds nothing.
    assert rival_staff.patch(fields_url(rival, shirt), {"label": "X"}, format="json").status_code == 404
    assert rival_staff.post(fields_url(rival, shirt, "retire/")).status_code == 404
    assert rival_staff.get(member_values_url(rival, member)).status_code == 404
    foreign = rival_staff.patch(
        member_values_url(rival, rival_member), {"values": {shirt["id"]: "M"}}, format="json"
    )
    assert foreign.status_code == 400
    assert (
        staff.patch(
            member_values_url(club, member), {"values": {rival_field["id"]: "M"}}, format="json"
        ).status_code
        == 400
    )
    assert not MemberFieldValue.objects.exists()

    # A player in both clubs sees each club's fields separately.
    both = add_member(rival, member.user)
    plain = logged_in(member.user)
    assert [e["field"]["id"] for e in plain.get(my_values_url(both)).json()] == [rival_field["id"]]
    assert [e["field"]["id"] for e in plain.get(my_values_url(member)).json()] == [shirt["id"]]


def test_values_end_with_access_but_survive_a_return(club, staff, member, shirt):
    plain = logged_in(member.user)
    plain.patch(my_values_url(member), {"values": {shirt["id"]: "S"}}, format="json")

    assert staff.post(f"{ORGS}{club.id}/members/{member.id}/remove/").status_code == 204
    assert plain.get(my_values_url(member)).status_code == 404
    assert plain.get(fields_url(club)).status_code == 403
    assert staff.get(member_values_url(club, member)).status_code == 404

    member.status = "active"
    member.save()
    assert values(plain.get(my_values_url(member))) == {"Shirt size": "S"}


def test_an_organization_has_a_limited_number_of_active_fields(club, staff):
    MemberField.objects.bulk_create(
        MemberField(organization=club, label=f"Field {n}", kind="text") for n in range(MAX_ACTIVE_FIELDS)
    )
    extra = staff.post(fields_url(club), {"label": "One more", "kind": "text"}, format="json")
    assert extra.status_code == 409 and code(extra) == "too_many_fields"

    first = staff.get(fields_url(club)).json()[0]
    staff.post(fields_url(club, first, "retire/"))
    make_field(staff, club, "One more")
    assert code(staff.post(fields_url(club, first, "restore/"))) == "too_many_fields"
