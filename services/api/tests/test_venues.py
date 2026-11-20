"""Venue and table setup (REQ-007, EVAL-007, TASK-017)."""

import pytest

from facilities.models import MAX_ACTIVE_TABLES, Table, Venue
from organizations.permissions import RoleKey

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, code, create_club

pytestmark = pytest.mark.django_db


def venues_url(org, venue=None, table=None):
    url = f"{ORGS}{org.id}/venues/"
    if venue:
        url += f"{venue['id']}/"
    if table is not None:
        url += "tables/" + (f"{table['id']}/" if table else "")
    return url


def make_venue(staff, club, name="Makadara Hall", **extra) -> dict:
    response = staff.post(venues_url(club), {"name": name, "town": "Mombasa", **extra}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def add_table(staff, club, venue, label) -> dict:
    response = staff.post(venues_url(club, venue, table=False), {"label": label}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_a_venue_carries_directions_and_coordinates(staff, club):
    venue = make_venue(staff, club, directions="Opposite the Total station on Moi Avenue.")
    assert venue["directions"] == "Opposite the Total station on Moi Avenue."
    assert (venue["latitude"], venue["longitude"]) == (None, None)
    pinned = staff.patch(venues_url(club, venue), {"latitude": -4.06, "longitude": 39.67}, format="json")
    assert (pinned.json()["latitude"], pinned.json()["longitude"]) == (-4.06, 39.67)
    half = staff.patch(venues_url(club, venue), {"longitude": None}, format="json")
    assert half.status_code == 400 and "longitude" in half.json()["fields"]


def test_staff_set_up_a_venue_and_its_tables(staff, club):
    venue = make_venue(staff, club, address="Makadara Road")
    assert venue["tables"] == [] and venue["active"] is True
    for label in ("Table 1", "Table 2", "Show table"):
        venue = add_table(staff, club, venue, label)
    assert [(t["label"], t["position"]) for t in venue["tables"]] == [
        ("Table 1", 0),
        ("Table 2", 1),
        ("Show table", 2),
    ]

    # A label is unique among the venue's tables in use, whatever its case.
    clash = staff.post(venues_url(club, venue, table=False), {"label": "table 1"}, format="json")
    assert clash.status_code == 400 and "label" in clash.json()["fields"]

    renamed = staff.patch(venues_url(club, venue, venue["tables"][2]), {"label": "Table 3"}, format="json")
    assert [t["label"] for t in renamed.json()["tables"]] == ["Table 1", "Table 2", "Table 3"]

    # A table is switched off, never deleted, and its label becomes free again.
    off = staff.patch(venues_url(club, venue, venue["tables"][0]), {"active": False}, format="json")
    assert [t["active"] for t in off.json()["tables"]] == [False, True, True]
    assert Table.objects.filter(venue_id=venue["id"]).count() == 3
    assert len(add_table(staff, club, venue, "Table 1")["tables"]) == 4
    back = staff.patch(venues_url(club, venue, venue["tables"][0]), {"active": True}, format="json")
    assert back.status_code == 400  # another table uses the label now

    edited = staff.patch(
        venues_url(club, venue), {"name": "Makadara Sports Hall", "town": "Nyali"}, format="json"
    )
    assert (edited.json()["name"], edited.json()["town"]) == ("Makadara Sports Hall", "Nyali")


def test_venue_names_are_unique_while_in_use(staff, club):
    venue = make_venue(staff, club)
    again = staff.post(venues_url(club), {"name": "makadara hall", "town": "Mombasa"}, format="json")
    assert again.status_code == 400 and "name" in again.json()["fields"]
    assert staff.post(venues_url(club), {"name": " ", "town": ""}, format="json").status_code == 400

    assert staff.patch(venues_url(club, venue), {"active": False}, format="json").json()["active"] is False
    make_venue(staff, club)  # the name is free once the first is switched off
    assert Venue.objects.filter(organization=club).count() == 2


def test_only_facility_managers_change_venues(club, staff):
    venue = add_table(staff, club, make_venue(staff, club), "Table 1")
    hidden = make_venue(staff, club, "Old Hall")
    staff.patch(venues_url(club, hidden), {"active": False}, format="json")
    staff.patch(
        venues_url(club, venue, add_table(staff, club, venue, "Broken")["tables"][1]),
        {"active": False},
        format="json",
    )

    member = logged_in(add_member(club, make_user("juma@example.com")).user)
    # Captains run competitions but don't manage facilities.
    captain = logged_in(add_member(club, make_user("cap@example.com"), RoleKey.CAPTAIN).user)
    outsider = logged_in(make_user("out@example.com"))
    rival = create_club(make_user("rival@example.com"), "Nyali Loop")
    rival_staff = logged_in(rival.memberships.get().user)

    # Members see the venues and tables in use; switched-off ones are for facility staff.
    for client in (member, captain):
        listed = client.get(venues_url(club)).json()
        assert [(v["name"], [t["label"] for t in v["tables"]]) for v in listed] == [
            ("Makadara Hall", ["Table 1"])
        ]
    assert {v["name"] for v in staff.get(venues_url(club)).json()} == {"Makadara Hall", "Old Hall"}
    assert len(staff.get(venues_url(club)).json()[0]["tables"]) == 2

    table = venue["tables"][0]
    for client in (member, captain, outsider, rival_staff):
        assert client.post(venues_url(club), {"name": "X", "town": "Y"}, format="json").status_code == 403
        assert client.patch(venues_url(club, venue), {"name": "X"}, format="json").status_code == 403
        assert (
            client.post(venues_url(club, venue, table=False), {"label": "T9"}, format="json").status_code
            == 403
        )
        assert client.patch(venues_url(club, venue, table), {"label": "T9"}, format="json").status_code == 403
    for client in (outsider, rival_staff):
        assert client.get(venues_url(club)).status_code == 403

    # Ids from one organization mean nothing in another.
    assert rival_staff.patch(venues_url(rival, venue), {"name": "Mine"}, format="json").status_code == 404
    other = make_venue(rival_staff, rival, "Nyali Gym")
    assert staff.patch(venues_url(club, other, table), {"label": "T9"}, format="json").status_code == 404
    assert Venue.objects.get(pk=venue["id"]).name == "Makadara Hall"


def test_a_venue_has_a_limited_number_of_tables_in_use(staff, club):
    venue = make_venue(staff, club)
    Table.objects.bulk_create(
        Table(venue_id=venue["id"], label=f"T{n}", position=n) for n in range(MAX_ACTIVE_TABLES)
    )
    full = staff.post(venues_url(club, venue, table=False), {"label": "One more"}, format="json")
    assert full.status_code == 409 and code(full) == "too_many_tables"
