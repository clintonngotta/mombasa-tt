"""The notification inbox, triggers, preferences and announcements (REQ-019, EVAL-019; TASK-033)."""

import pytest

from competitions.models import Match, Tournament
from notifications import service
from notifications.models import Notification
from reservations import board

from .helpers import logged_in, make_user
from .test_entries import act, cup, enter, player, singles  # noqa: F401
from .test_reservations import hall, person, recall, send, started, tables  # noqa: F401
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db
INBOX = "/api/v1/me/notifications/"


def alerts(user, **filters):
    return list(Notification.objects.filter(recipient=user, **filters).order_by("created_at"))


def test_the_same_event_sent_ten_times_is_one_alert_and_a_new_version_supersedes(club):
    amina = make_user("amina@example.com")
    for _ in range(10):
        service.notify([amina], "announcement", "Hello", subject="x:1", version="1")
    assert len(alerts(amina)) == 1
    service.notify([amina], "announcement", "Hello again", subject="x:1", version="2")
    old, new = alerts(amina)
    assert (old.superseded, new.superseded) == (True, False)


def test_registration_decisions_reach_the_players(staff, cup, singles):  # noqa: F811
    ama = player("Ama")
    entry = enter(logged_in(ama), cup, singles)
    assert alerts(ama) == []
    act(staff, cup, singles, entry, "waitlist")
    act(staff, cup, singles, entry, "accept")
    waited, accepted = alerts(ama, category="registration")
    assert waited.superseded and not accepted.superseded
    assert accepted.title.startswith("You're in") and accepted.link == f"/tournaments/{cup['id']}"


def test_a_table_call_and_a_recall(staff, club, hall):  # noqa: F811
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    send(staff, game, tables(hall)[0])
    amina = person("Amina")
    called = alerts(amina, category="table_call")
    assert [a.title for a in called] == ["Called to Table 1"]
    recall(staff, game)
    called[0].refresh_from_db()
    assert called[0].superseded is True  # opening it shows the match as it is now
    assert [a.title for a in alerts(amina, category="assignment")] == ["Your match was taken off its table"]
    send(staff, game, tables(hall)[1])
    assert [a.title for a in alerts(amina, category="table_call", superseded=False)] == ["Called to Table 2"]


def test_the_inbox_is_the_players_own(club):
    amina, brian = make_user("amina@example.com"), make_user("brian@example.com")
    service.notify([amina], "announcement", "One", subject="a:1")
    service.notify([amina], "announcement", "Two", subject="a:2")
    me = logged_in(amina)
    assert [a["title"] for a in me.get(INBOX).json()["results"]] == ["Two", "One"]
    assert me.get(f"{INBOX}unread-count/").json() == {"unread": 2}
    first = me.get(INBOX).json()["results"][0]
    assert logged_in(brian).post(f"{INBOX}{first['id']}/read/").status_code == 404
    assert me.post(f"{INBOX}{first['id']}/read/").json()["read"] is True
    assert [a["title"] for a in me.get(INBOX, {"unread": "true"}).json()["results"]] == ["One"]
    me.post(f"{INBOX}read-all/")
    assert me.get(f"{INBOX}unread-count/").json() == {"unread": 0}
    assert logged_in(brian).get(INBOX).json()["results"] == []


def test_preferences_switch_categories_off_but_not_the_table_call(club):
    amina = make_user("amina@example.com")
    me = logged_in(amina)
    prefs = me.get("/api/v1/me/notification-preferences/").json()["preferences"]
    assert all(p["enabled"] for p in prefs)
    assert [p["category"] for p in prefs if p["locked"]] == ["table_call"]
    me.put(
        "/api/v1/me/notification-preferences/",
        {
            "preferences": [
                {"category": "soda", "enabled": False},
                {"category": "table_call", "enabled": False},
            ]
        },
        format="json",
    )
    shown = {
        p["category"]: p["enabled"]
        for p in me.get("/api/v1/me/notification-preferences/").json()["preferences"]
    }
    assert (shown["soda"], shown["table_call"]) == (False, True)
    service.notify([amina], "soda", "Challenge", subject="soda:1")
    service.notify([amina], "table_call", "Called", subject="match:1")
    assert [a.category for a in alerts(amina)] == ["table_call"]


def test_announcements_go_to_an_explicit_audience_only(club, staff):
    members = []
    for name in ("Amina", "Brian"):
        user = make_user(f"{name.lower()}@example.com", display_name=name)
        add_member(club, user)
        members.append(user)
    outsider = make_user("outsider@example.com")
    path = f"{ORGS}{club.id}/announcements/"
    sent = staff.post(path, {"title": "Hall closed Friday", "audience": "members"}, format="json").json()
    assert sent["sent"] == 3  # the two members and the admin
    assert alerts(outsider) == []
    named = staff.post(
        path, {"title": "See me", "audience": "people", "user_ids": [str(members[0].id)]}, format="json"
    )
    assert named.json()["sent"] == 1
    refused = staff.post(
        path, {"title": "x", "audience": "people", "user_ids": [str(outsider.id)]}, format="json"
    )
    assert refused.status_code == 400
    assert (
        logged_in(members[1]).post(path, {"title": "x", "audience": "members"}, format="json").status_code
        == 403
    )


def test_the_matches_next_in_line_hear_they_are_up_next_and_the_call_supersedes_it(staff, club, hall):  # noqa: F811
    names = [[n] for n in ("Amina", "Brian", "Chao", "Dalia", "Eli", "Fatma", "Gideon", "Halima")]
    game = started(staff, club, hall, names)
    one, two = tables(hall)
    send(staff, game, one)  # two tables, four ready matches: one goes out, one could, two wait
    first = set(players_of(game["match"]))
    told = Notification.objects.filter(category="up_next", superseded=False)
    told_people = {alert.recipient_id for alert in told}
    assert len(told_people) == 4 and not told_people & first
    assert {alert.title for alert in told} == {"You're up next"}
    # Calling one of them to a table supersedes its "Up next" with the call.
    waiting = next(
        m
        for m in Match.objects.filter(draw__event_id=game["event"]["id"], round=1)
        if set(players_of(m)) <= told_people
    )
    send(staff, {**game, "match": waiting}, two)
    for user_id in players_of(waiting):
        assert not Notification.objects.filter(
            recipient_id=user_id, category="up_next", superseded=False
        ).exists()
        assert Notification.objects.filter(
            recipient_id=user_id, category="table_call", superseded=False
        ).exists()
    # Sending the same alert again changes nothing: each match is announced once.
    count = Notification.objects.filter(category="up_next").count()

    board.announce_up_next(Tournament.objects.get(pk=game["cup"]["id"]))
    assert Notification.objects.filter(category="up_next").count() == count


def players_of(match):
    return [p.user_id for entry in (match.entry_a, match.entry_b) for p in entry.players.all()]
