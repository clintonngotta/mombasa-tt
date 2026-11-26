"""Club penalties for absences (REQ-054, TASK-129): rules, proposals from missed training, tournament
entries and squad places, apologies that excuse, issuing with a fine, waiving, appeals, suspensions from
selection, and who sees what."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from competitions.models import Entry, EntryPlayer, Event, Tournament
from finance.models import Charge
from notifications.models import Notification
from organizations.models import Role
from penalties.models import AbsencePenalty
from squads.models import Squad, SquadPlace
from training.models import ClubSession, SessionInvitation

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member
from .test_tournaments import add_event, make_tournament

pytestmark = pytest.mark.django_db
MINE = "/api/v1/me/absence-penalties/"


def url(club, tail=""):
    return f"{ORGS}{club.id}/{tail}"


@pytest.fixture
def world(club, staff):
    """The club admin (staff), a governance officer without the finance permission, three members and an
    outsider."""
    officer = make_user("officer@example.com", display_name="Officer")
    add_member(
        club, officer, Role.objects.create(organization=club, name="Gov", permissions=["governance.manage"])
    )
    users = {
        name: make_user(f"{name}@example.com", display_name=name.title())
        for name in ("ann", "ben", "cat", "outsider")
    }
    for name in ("ann", "ben", "cat"):
        add_member(club, users[name])
    made = {"club": club, "staff": staff, "officer": logged_in(officer), "users": users}
    made.update({name: logged_in(user) for name, user in users.items()})
    cache.clear()  # the logins above used up the login allowance
    return made


def rules(world, client=None, **training):
    body = {"rules": [{"applies_to": "training", "kind": "warning", **training}]}
    return (client or world["staff"]).put(url(world["club"], "absence-rules/"), body, format="json")


def missed_session(
    world, name, *, days_ago=2, status="accepted", attended=False, apologised=False
) -> SessionInvitation:
    starts = timezone.now() - timedelta(days=days_ago)
    session = ClubSession.objects.create(
        organization=world["club"],
        title=f"Squad {days_ago}",
        starts_at=starts,
        ends_at=starts + timedelta(hours=2),
    )
    return SessionInvitation.objects.create(
        session=session,
        user=world["users"][name],
        status=status,
        attended=attended,
        apologised_at=starts - timedelta(hours=3) if apologised else None,
    )


def propose(world, client=None):
    return (client or world["staff"]).post(
        url(world["club"], "absence-penalties/propose/"), {}, format="json"
    )


def penalties(world, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return world["staff"].get(url(world["club"], f"absence-penalties/?{query}")).json()


def test_governance_staff_set_the_rules_and_a_fine_takes_finance_too(world):
    club = world["club"]
    for who in ("ann", "outsider"):
        assert world[who].get(url(club, "absence-rules/")).status_code == 403
        assert rules(world, world[who]).status_code == 403
        assert world[who].get(url(club, "absence-penalties/")).status_code == 403
        assert propose(world, world[who]).status_code == 403
    assert rules(world, world["officer"], kind="points", points=2).status_code == 200
    # The officer holds no finance permission: a fine is refused; the admin may set one.
    assert rules(world, world["officer"], fine_minor=20000).status_code == 403
    saved = rules(world, fine_minor=20000, kind="suspension", suspension_events=2)
    assert saved.status_code == 200, saved.json()
    assert saved.json()[0]["fine_minor"] == 20000 and saved.json()[0]["suspension_events"] == 2
    for bad in (
        {"rules": [{"applies_to": "training", "kind": "suspension"}]},
        {"rules": [{"applies_to": "training", "kind": "points"}]},
        {"rules": [{"applies_to": "meeting"}]},
        {"rules": [{"applies_to": "training"}, {"applies_to": "training"}]},
        {"rules": [{"applies_to": "training", "severity": 3}]},
        {"rules": [], "extra": 1},
    ):
        assert world["staff"].put(url(club, "absence-rules/"), bad, format="json").status_code == 400, bad
    # Sending the list replaces it.
    assert world["staff"].put(url(club, "absence-rules/"), {"rules": []}, format="json").json() == []


def test_the_app_proposes_for_missed_training_and_an_apology_excuses(world):
    rules(world)
    missed_session(world, "ann")  # accepted and stayed away
    missed_session(world, "ben", status="declined", apologised=True, days_ago=3)  # apologised in time
    missed_session(world, "cat", attended=True, days_ago=4)  # came
    missed_session(world, "ann", days_ago=120)  # too long ago
    assert propose(world).json() == {"proposed": 1}
    assert propose(world).json() == {"proposed": 0}  # nothing twice
    found = penalties(world)
    assert [(p["member_name"], p["what"], p["status"], p["kind"]) for p in found] == [
        ("Ann", "Squad 2", "proposed", "warning")
    ]
    # Nothing is decided yet, so the member sees nothing and isn't told.
    assert (
        world["ann"].get(MINE).json() == [] and Notification.objects.filter(category="penalty").count() == 0
    )

    # When the club decides an apology doesn't excuse, the one who apologised is proposed too.
    rules(world, apology_excuses=False)
    assert propose(world).json() == {"proposed": 1}
    assert sorted(p["member_name"] for p in penalties(world)) == ["Ann", "Ben"]
    # A rule switched off proposes nothing.
    missed_session(world, "cat", days_ago=5)
    rules(world, active=False)
    assert propose(world).json() == {"proposed": 0}


def test_issuing_charges_the_fine_and_waiving_takes_a_reason(world):
    club = world["club"]
    rules(world, fine_minor=20000)
    missed_session(world, "ann")
    missed_session(world, "ben", days_ago=3)
    propose(world)
    by_name = {p["member_name"]: p for p in penalties(world)}
    issue = url(club, f"absence-penalties/{by_name['Ann']['id']}/issue/")
    assert world["ann"].post(issue, {}, format="json").status_code == 403
    issued = world["officer"].post(issue, {"reason": "Second time this month"}, format="json")
    assert issued.status_code == 200, issued.json()
    assert (issued.json()["status"], issued.json()["decided_by_name"]) == ("issued", "Officer")
    charge = Charge.objects.get(member=world["users"]["ann"])
    assert (charge.amount_minor, charge.purpose, charge.waived_at) == (20000, "Penalty: Squad 2", None)
    assert world["officer"].post(issue, {}, format="json").json()["code"] == "already_decided"
    assert Charge.objects.count() == 1
    assert Notification.objects.filter(
        recipient=world["users"]["ann"], title="A penalty was issued to you"
    ).exists()

    # The member sees their own penalty and nobody else's.
    mine = world["ann"].get(MINE).json()
    assert [(p["what"], p["status"], p["fine_minor"], p["can_appeal"]) for p in mine] == [
        ("Squad 2", "issued", 20000, True)
    ]
    assert world["ben"].get(MINE).json() == [] and world["cat"].get(MINE).json() == []

    # Waiving needs a reason; a proposed one is waived without anyone being charged.
    waive = url(club, f"absence-penalties/{by_name['Ben']['id']}/waive/")
    assert world["officer"].post(waive, {}, format="json").status_code == 400
    waived = world["officer"].post(waive, {"reason": "He was at a funeral"}, format="json").json()
    assert (waived["status"], waived["reason"]) == ("waived", "He was at a funeral")
    assert Charge.objects.count() == 1
    assert [p["status"] for p in world["ben"].get(MINE).json()] == ["waived"]
    # Waiving an issued penalty waives its fine.
    world["staff"].post(
        url(club, f"absence-penalties/{by_name['Ann']['id']}/waive/"), {"reason": "Mistake"}, format="json"
    )
    assert Charge.objects.get(pk=charge.pk).waived_at is not None
    assert [p["member_name"] for p in penalties(world, status="proposed")] == []


def test_a_member_appeals_once_and_an_upheld_appeal_waives_the_penalty(world):
    club = world["club"]
    rules(world, fine_minor=20000)
    missed_session(world, "ann")
    missed_session(world, "ben", days_ago=3)
    propose(world)
    by_name = {p["member_name"]: p for p in penalties(world)}
    for name in ("Ann", "Ben"):
        world["staff"].post(url(club, f"absence-penalties/{by_name[name]['id']}/issue/"), {}, format="json")
    ann = f"{MINE}{by_name['Ann']['id']}/appeal/"
    # Only the member appeals their own penalty.
    assert world["ben"].post(ann, {"text": "x"}, format="json").status_code == 404
    assert world["staff"].post(ann, {"text": "x"}, format="json").status_code == 404
    assert world["ann"].post(ann, {}, format="json").status_code == 400
    appealed = world["ann"].post(ann, {"text": "I was marked absent but I was there."}, format="json")
    assert appealed.status_code == 200 and (appealed.json()["appeal"], appealed.json()["can_appeal"]) == (
        "pending",
        False,
    )
    assert world["ann"].post(ann, {"text": "Again"}, format="json").json()["code"] == "already_appealed"

    decide = url(club, f"absence-penalties/{by_name['Ann']['id']}/appeal/")
    assert world["ann"].post(decide, {"upheld": True}, format="json").status_code == 403
    upheld = (
        world["officer"]
        .post(decide, {"upheld": True, "note": "The register was wrong"}, format="json")
        .json()
    )
    assert (upheld["status"], upheld["appeal"], upheld["reason"]) == (
        "waived",
        "upheld",
        "The register was wrong",
    )
    assert Charge.objects.get(member=world["users"]["ann"]).waived_at is not None
    assert world["officer"].post(decide, {"upheld": False}, format="json").json()["code"] == "no_appeal"

    # A rejected appeal leaves the penalty standing, and there is no second appeal.
    ben = f"{MINE}{by_name['Ben']['id']}/appeal/"
    world["ben"].post(ben, {"text": "Unfair"}, format="json")
    rejected = (
        world["officer"]
        .post(
            url(club, f"absence-penalties/{by_name['Ben']['id']}/appeal/"),
            {"upheld": False, "note": "No"},
            format="json",
        )
        .json()
    )
    assert (rejected["status"], rejected["appeal"]) == ("issued", "rejected")
    assert world["ben"].post(ben, {"text": "Again"}, format="json").json()["code"] == "already_appealed"
    assert Charge.objects.get(member=world["users"]["ben"]).waived_at is None


def test_tournament_no_shows_and_squad_absences_are_proposed(world):
    club, staff, users = world["club"], world["staff"], world["users"]
    staff.put(
        url(club, "absence-rules/"),
        {
            "rules": [
                {"applies_to": "tournament", "kind": "points", "points": 3},
                {"applies_to": "squad", "kind": "warning"},
            ]
        },
        format="json",
    )
    tournament = make_tournament(staff, club)
    add_event(staff, tournament)
    event = Event.objects.get(tournament_id=tournament["id"])
    ended = timezone.localdate() - timedelta(days=3)
    Tournament.objects.filter(pk=tournament["id"]).update(status="completed", starts_on=ended, ends_on=ended)
    for name, checked in (("ann", None), ("ben", timezone.now()), ("outsider", None)):
        entry = Entry.objects.create(
            event=event, status="accepted", entered_by=users[name], checked_in_at=checked
        )
        EntryPlayer.objects.create(
            entry=entry, event=event, user=users[name], live=True, checked_in_at=checked
        )
    squad = Squad.objects.create(
        organization=club,
        title="Nairobi Open",
        starts_on=ended,
        ends_on=ended,
        status="published",
        published_at=timezone.now() - timedelta(days=10),
        slots=[{"id": "a" * 12, "label": "Team", "places": 2}],
    )
    cat = SquadPlace.objects.create(squad=squad, slot="a" * 12, user=users["cat"], status="accepted")
    went = SquadPlace.objects.create(squad=squad, slot="a" * 12, user=users["ben"], status="accepted")
    # Nothing about the squad until staff record who went.
    assert propose(world).json() == {"proposed": 1}
    place = url(club, f"squads/{squad.id}/places/")
    assert (
        world["cat"].post(f"{place}{cat.id}/attendance/", {"attended": True}, format="json").status_code
        == 403
    )
    assert staff.post(f"{place}{cat.id}/attendance/", {"attended": False}, format="json").status_code == 200
    assert staff.post(f"{place}{went.id}/attendance/", {"attended": True}, format="json").status_code == 200
    assert propose(world).json() == {"proposed": 1}
    found = {(p["member_name"], p["applies_to"], p["kind"], p["points"]) for p in penalties(world)}
    # The member who didn't check in and the one who didn't go; never the outsider, who isn't a member.
    assert found == {("Ann", "tournament", "points", 3), ("Cat", "squad", "warning", None)}


def test_a_suspension_puts_the_member_last_in_the_rotation_until_it_is_served(world):
    club, staff, users = world["club"], world["staff"], world["users"]
    rules(world, kind="suspension", suspension_events=1)
    missed_session(world, "ann")
    propose(world)
    penalty = penalties(world)[0]
    staff.post(url(club, f"absence-penalties/{penalty['id']}/issue/"), {}, format="json")

    def squad(title, days):
        body = {
            "title": title,
            "starts_on": str(timezone.localdate() + timedelta(days=days)),
            "ends_on": str(timezone.localdate() + timedelta(days=days)),
            "slots": [{"label": "Team", "places": 6}],
        }
        return staff.post(url(club, "squads/"), body, format="json").json()

    first = squad("First away", 20)
    order = staff.get(url(club, f"squads/{first['id']}/recommendation/")).json()
    assert order[-1]["display_name"] == "Ann" and order[-1]["suspended"] is True
    # Picking her anyway takes a reason, even with places free for everyone.
    pick = {"user_id": str(users["ann"].id), "slot": first["slots"][0]["id"]}
    assert (
        staff.post(url(club, f"squads/{first['id']}/places/"), pick, format="json").json()["code"]
        == "reason_required"
    )
    # Once one squad has been published since, the suspension is served.
    staff.post(
        url(club, f"squads/{first['id']}/places/"), {**pick, "user_id": str(users["ben"].id)}, format="json"
    )
    staff.post(url(club, f"squads/{first['id']}/publish/"), {}, format="json")
    second = squad("Second away", 40)
    order = staff.get(url(club, f"squads/{second['id']}/recommendation/")).json()
    assert not any(row["suspended"] for row in order)
    assert AbsencePenalty.objects.get().status == "issued"
