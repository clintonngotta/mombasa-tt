"""Representative squads (REQ-050, TASK-123): slots, picking in rotation with a reason for overrides,
players accepting or declining, staff replacing, history, and who sees what."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from notifications.models import Notification
from organizations.models import Role
from ratings.models import Rating
from squads.models import Squad, SquadPlace

from .helpers import logged_in, make_user
from .test_representatives import make_body
from .test_roles import ORGS, add_member, create_club

pytestmark = pytest.mark.django_db
MINE = "/api/v1/me/squad-places/"


def url(org, squad=None, tail=""):
    return f"{ORGS}{org.id}/squads/" + (f"{squad['id']}/{tail}" if squad else tail)


def day(offset):
    return str(timezone.localdate() + timedelta(days=offset))


@pytest.fixture
def world(club, staff):
    """A club with five members rated 1500 down to 1100, a selector who only runs competitions, and an
    outsider."""
    selector = make_user("selector@example.com", display_name="Selector")
    add_member(
        club,
        selector,
        Role.objects.create(organization=club, name="Selector", permissions=["competitions.manage"]),
    )
    users = {}
    for index, name in enumerate(["ann", "ben", "cat", "dan", "eve"]):
        users[name] = make_user(f"{name}@example.com", display_name=name.title())
        add_member(club, users[name])
        Rating.objects.create(user=users[name], discipline="singles", rating=1500 - 100 * index)
    users["outsider"] = make_user("outsider@example.com", display_name="Outsider")
    made = {"club": club, "staff": staff, "selector": logged_in(selector), "users": users}
    made.update({name: logged_in(user) for name, user in users.items()})
    cache.clear()  # the logins above used up the login allowance
    return made


def new_squad(world, client=None, starts=30, **extra) -> dict:
    body = {
        "title": "Nairobi Open",
        "starts_on": day(starts),
        "ends_on": day(starts + 1),
        "slots": [{"label": "Men's team", "places": 2}, {"label": "Reserve", "places": 1}],
        **extra,
    }
    made = (client or world["selector"]).post(url(world["club"]), body, format="json")
    assert made.status_code == 201, made.json()
    return made.json()


def pick(world, squad, name, slot=0, client=None, **extra):
    body = {"user_id": str(world["users"][name].id), "slot": squad["slots"][slot]["id"], **extra}
    return (client or world["selector"]).post(url(world["club"], squad, "places/"), body, format="json")


def place_of(world, squad, name) -> SquadPlace:
    return SquadPlace.objects.filter(squad_id=squad["id"], user=world["users"][name]).latest("picked_at")


PLAYERS = {"Ann", "Ben", "Cat", "Dan", "Eve"}


def names(rows) -> list[str]:
    """The five rated players in the order given (the club's admin and selector are members too)."""
    return [row["display_name"] for row in rows if row["display_name"] in PLAYERS]


def played(world, title, starts, *who) -> dict:
    """A published squad in the past that these players accepted."""
    squad = new_squad(world, title=title, starts=starts)
    for name in who:
        SquadPlace.objects.create(
            squad_id=squad["id"], slot=squad["slots"][0]["id"], user=world["users"][name], status="accepted"
        )
    Squad.objects.filter(pk=squad["id"]).update(status="published")
    return squad


def test_staff_build_a_squad_with_slots_and_only_staff_see_it(world):
    club = world["club"]
    squad = new_squad(world)
    assert [(s["label"], s["places"]) for s in squad["slots"]] == [("Men's team", 2), ("Reserve", 1)]
    assert squad["status"] == "draft" and squad["discipline"] == "singles"
    for who in ("ann", "outsider"):
        assert world[who].get(url(club)).status_code == 403
        assert world[who].get(url(club, squad)).status_code == 403
        assert world[who].post(url(club), {"title": "x"}, format="json").status_code == 403
        assert world[who].get(url(club, squad, "recommendation/")).status_code == 403
        assert world[who].get(url(club, tail="history/")).status_code == 403
    for bad in (
        {"slots": []},
        {"slots": [{"label": "Team", "places": 0}]},
        {"ends_on": day(1), "starts_on": day(5)},
        {"owner": "x"},
        {"external_event_id": "00000000-0000-4000-8000-000000000000"},
    ):
        assert world["selector"].patch(url(club, squad), bad, format="json").status_code == 400, bad
    # Slots keep their ids when edited; a draft can be deleted.
    kept = squad["slots"][0]
    edited = (
        world["selector"]
        .patch(
            url(club, squad),
            {"slots": [{**kept, "places": 3}, {"label": "Women's singles", "places": 2}]},
            format="json",
        )
        .json()
    )
    assert edited["slots"][0] == {**kept, "places": 3} and edited["slots"][1]["id"] != squad["slots"][1]["id"]
    assert world["selector"].delete(url(club, squad)).status_code == 204


def test_the_rotation_puts_the_least_recently_represented_first(world):
    club = world["club"]
    # Nobody has represented yet: the order is by rating.
    squad = new_squad(world)
    order = world["selector"].get(url(club, squad, "recommendation/")).json()
    assert names(order) == ["Ann", "Ben", "Cat", "Dan", "Eve"]
    assert order[0]["rating"] == 1500 and order[0]["last_represented_on"] is None

    # Ann and Ben went to an older tournament, Cat and Dan to the latest one.
    played(world, "County Cup", -60, "ann", "ben")
    played(world, "Coast Classic", -20, "cat", "dan")
    order = world["selector"].get(url(club, squad, "recommendation/")).json()
    # Eve never went; then those who went longest ago, by rating; the last squad goes last.
    assert names(order) == ["Eve", "Ann", "Ben", "Cat", "Dan"]
    five = [row for row in order if row["display_name"] in PLAYERS]
    assert [row["in_previous_squad"] for row in five] == [False, False, False, True, True]
    assert five[1]["last_represented_on"] == day(-60)
    # The outsider is nobody the club can pick.
    assert "Outsider" not in [row["display_name"] for row in order]


def test_picking_outside_the_rotation_takes_a_reason(world):
    club = world["club"]
    played(world, "County Cup", -60, "ann", "ben")
    squad = new_squad(world)  # the rotation: Cat, Dan, Eve (never went), then Ann, Ben
    refused = pick(world, squad, "ann")
    assert refused.status_code == 400 and refused.json()["code"] == "reason_required"
    assert pick(world, squad, "cat").status_code == 201  # next in the rotation: no reason needed
    overridden = pick(world, squad, "ann", reason="Our only left-hander")
    assert overridden.status_code == 201, overridden.json()
    places = {p["display_name"]: p for p in overridden.json()["places"]}
    assert (places["Cat"]["recommended"], places["Cat"]["override_reason"]) == (True, "")
    assert (places["Ann"]["recommended"], places["Ann"]["override_reason"]) == (False, "Our only left-hander")

    # A full slot, the same player twice, a slot that isn't there, and someone who isn't a member.
    assert pick(world, squad, "dan").json()["code"] == "slot_full"
    assert pick(world, squad, "cat", slot=1).json()["code"] == "already_picked"
    assert (
        world["selector"]
        .post(
            url(club, squad, "places/"),
            {"user_id": str(world["users"]["dan"].id), "slot": "0" * 12},
            format="json",
        )
        .json()["code"]
        == "no_such_slot"
    )
    assert pick(world, squad, "outsider", slot=1, reason="x").json()["code"] == "not_eligible"
    assert pick(world, squad, "dan", slot=1, client=world["ann"]).status_code == 403
    # A slot can't shrink below the players in it.
    shrunk = world["selector"].patch(
        url(club, squad), {"slots": [{**squad["slots"][0], "places": 1}, squad["slots"][1]]}, format="json"
    )
    assert shrunk.status_code == 409 and shrunk.json()["code"] == "slot_in_use"


def test_players_answer_once_published_and_staff_replace_who_declines(world):
    club = world["club"]
    squad = new_squad(world)
    pick(world, squad, "ann")
    pick(world, squad, "ben")
    # A draft tells nobody and isn't the player's to see or answer.
    assert Notification.objects.filter(category="squad").count() == 0
    assert world["ann"].get(MINE).json() == []
    ann = place_of(world, squad, "ann")
    assert world["ann"].post(f"{MINE}{ann.id}/accept/", {}, format="json").status_code == 404

    out = world["selector"].post(url(club, squad, "publish/"), {}, format="json").json()
    assert out["status"] == "published"
    told = Notification.objects.filter(title="You're picked: Nairobi Open")
    assert sorted(told.values_list("recipient__display_name", flat=True)) == ["Ann", "Ben"]
    assert world["selector"].delete(url(club, squad)).json()["code"] == "squad_published"

    mine = world["ann"].get(MINE).json()
    assert [(p["squad"]["title"], p["slot_label"], p["status"]) for p in mine] == [
        ("Nairobi Open", "Men's team", "picked")
    ]
    # Only the player answers their own place.
    assert world["ben"].post(f"{MINE}{ann.id}/accept/", {}, format="json").status_code == 404
    assert world["selector"].post(f"{MINE}{ann.id}/accept/", {}, format="json").status_code == 404
    assert world["ann"].post(f"{MINE}{ann.id}/accept/", {}, format="json").json()["status"] == "accepted"
    ben = place_of(world, squad, "ben")
    assert world["ben"].post(f"{MINE}{ben.id}/decline/", {}, format="json").json()["status"] == "declined"
    assert world["ben"].post(f"{MINE}{ben.id}/accept/", {}, format="json").json()["code"] == "place_closed"
    assert "Ben declined: Nairobi Open" in Notification.objects.filter(category="squad").values_list(
        "title", flat=True
    )

    # The place Ben left is free again: staff fill it, and the new player is told at once.
    replaced = pick(world, squad, "cat")
    assert replaced.status_code == 201, replaced.json()
    assert Notification.objects.filter(
        recipient=world["users"]["cat"], title="You're picked: Nairobi Open"
    ).exists()
    # A player who accepted sees who else is in, by name.
    cat = place_of(world, squad, "cat")
    world["cat"].post(f"{MINE}{cat.id}/accept/", {}, format="json")
    assert world["ann"].get(MINE).json()[0]["teammates"] == ["Cat"]

    # Staff take a player out; they are told and the place is free.
    removed = world["selector"].post(url(club, squad, f"places/{cat.id}/remove/"), {}, format="json").json()
    assert {p["display_name"]: p["status"] for p in removed["places"]}["Cat"] == "removed"
    assert world["ann"].get(MINE).json()[0]["teammates"] == []

    # Once the tournament has started, answers are closed.
    dan = SquadPlace.objects.create(
        squad_id=squad["id"], slot=squad["slots"][1]["id"], user=world["users"]["dan"]
    )
    Squad.objects.filter(pk=squad["id"]).update(starts_on=timezone.localdate())
    assert world["dan"].post(f"{MINE}{dan.id}/accept/", {}, format="json").json()["code"] == "squad_started"


def test_history_is_the_players_own_and_the_staffs_for_everyone(world):
    club = world["club"]
    played(world, "County Cup", -60, "ann", "ben")
    played(world, "Coast Classic", -20, "ann")
    mine = world["ann"].get(MINE).json()
    assert [p["squad"]["title"] for p in mine] == ["Coast Classic", "County Cup"]
    assert world["cat"].get(MINE).json() == []
    rows = world["selector"].get(url(club, tail="history/")).json()
    assert [(r["display_name"], r["times"], r["last_represented_on"]) for r in rows] == [
        ("Ann", 2, day(-20)),
        ("Ben", 1, day(-60)),
    ]
    assert rows[0]["squads"] == ["Coast Classic", "County Cup"]


def test_a_regional_body_picks_from_its_regions_clubs_and_sees_names_and_clubs_only(world):
    club = world["club"]
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    elsewhere = create_club(make_user("kilifi@example.com", display_name="Kilifi Admin"), name="Kilifi TT")
    elsewhere.country, elsewhere.region = "KE", "Kilifi"
    elsewhere.save(update_fields=["country", "region"])
    far = make_user("far@example.com", display_name="Far Player", phone="+254700000009")
    add_member(elsewhere, far)
    chair = make_user("chair@example.com", display_name="Chair")
    body = make_body("Mombasa Region TT", chair)
    desk = logged_in(chair)
    made = desk.post(
        url(body),
        {
            "title": "Nationals",
            "starts_on": day(40),
            "ends_on": day(41),
            "slots": [{"label": "Team", "places": 2}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    squad = made.json()
    order = desk.get(url(body, squad, "recommendation/")).json()
    assert "Ann" in names(order) and "Far Player" not in [row["display_name"] for row in order]
    assert {row["club"] for row in order} == {club.name}
    picked = desk.post(
        url(body, squad, "places/"),
        {"user_id": str(world["users"]["ann"].id), "slot": squad["slots"][0]["id"]},
        format="json",
    )
    assert picked.status_code == 201, picked.json()
    place = picked.json()["places"][0]
    assert (place["display_name"], place["club"]) == ("Ann", club.name)
    # Nothing else about the player reaches the body, and the club's own staff don't see the body's squad.
    text = str(picked.json()) + str(order)
    assert "ann@example.com" not in text and "phone" not in text
    assert world["selector"].get(url(body, squad)).status_code == 403
    far_pick = desk.post(
        url(body, squad, "places/"),
        {"user_id": str(far.id), "slot": squad["slots"][0]["id"], "reason": "x"},
        format="json",
    )
    assert far_pick.json()["code"] == "not_eligible"
