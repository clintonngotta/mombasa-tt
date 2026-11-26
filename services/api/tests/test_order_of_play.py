"""The order of play (REQ-053, EVAL-053, TASK-127): stage order with dispatch fall-through, the release
window, a player's not-before and moving a match later."""

from datetime import date, datetime, timedelta

import pytest

from competitions.models import Entry, Match, MatchDayLog, NotBefore, ScheduleVersion, Tournament
from notifications.models import Notification
from reservations import board

from .helpers import logged_in
from .test_ratings import work
from .test_reservations import person, send
from .test_schedule import at, cup, hall, keep, people, publish, recommend  # noqa: F401
from .test_tournaments import do, url

pytestmark = pytest.mark.django_db


def order(client, cup, expect=200) -> dict:  # noqa: F811
    response = client.get(url(cup) + "order-of-play/")
    assert response.status_code == expect, response.json()
    return response.json()


def put(client, cup, path, body, expect=200) -> dict:  # noqa: F811
    response = client.put(url(cup) + "order-of-play/" + path, body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def plan_and_publish(staff, cup) -> list[dict]:  # noqa: F811
    slots = recommend(staff, cup)["slots"]
    keep(staff, cup, [{k: s[k] for k in ("match_id", "table_id", "scheduled_at")} for s in slots])
    publish(staff, cup)
    return slots


def tournament_of(cup) -> Tournament:  # noqa: F811
    return Tournament.objects.get(pk=cup["id"])


def release_now(cup) -> None:  # noqa: F811
    Tournament.objects.filter(pk=cup["id"]).update(order_of_play_release_at=datetime.now().astimezone())


def amina_matches() -> list[Match]:
    return [
        m for m in Match.objects.filter(draw__event__tournament__name="Coast Open") if "Amina" in names(m)
    ]


def names(match: Match) -> set:
    return {
        place.user.display_name
        for entry in (match.entry_a, match.entry_b)
        if entry
        for place in entry.players.all()
    }


def start_everything(staff, cup) -> None:  # noqa: F811
    for event in cup["events"]:
        for entry in Entry.objects.filter(event_id=event["id"]):
            staff.post(url(cup, event=event) + f"entries/{entry.id}/check-in/", {}, format="json")
    do(staff, cup, "start")
    for event in cup["events"]:
        do(staff, cup, "start", event=event)


def test_the_order_of_play_stays_with_staff_until_its_release_then_everyone_is_told(staff, cup):  # noqa: F811
    outsider = logged_in(person("Onlooker"))
    assert order(outsider, cup)["published"] is False
    # Nothing to release before a schedule is published.
    assert put(staff, cup, "release/", {"release_at": None}, 409)["code"] == "nothing_published"
    plan_and_publish(staff, cup)
    # First publication: out three days before play starts at 09:00 on 5 December.
    shown = order(staff, cup)
    assert at(shown["release_at"]) == at("2026-12-02T09:00:00+03:00") == at(shown["earliest_release"])
    assert shown["can_manage"] and not shown["released"] and len(shown["slots"]) == 9
    hidden = order(outsider, cup)
    assert (hidden["released"], hidden["slots"], hidden["stages"], hidden["players"]) == (False, [], [], [])
    league = cup["events"][0]
    first = Match.objects.filter(draw__event_id=league["id"]).order_by("round", "position").first()
    page = url(cup, event=league) + f"matches/{first.id}/"
    assert outsider.get(page).json()["scheduled_at"] is None
    assert staff.get(page).json()["scheduled_at"] is not None
    # Inside the window only.
    too_early = put(staff, cup, "release/", {"release_at": "2026-12-01T09:00:00+03:00"}, 400)
    assert "release_at" in too_early["fields"]
    assert (
        "release_at"
        in put(staff, cup, "release/", {"release_at": "2026-12-05T10:00:00+03:00"}, 400)["fields"]
    )
    later = put(staff, cup, "release/", {"release_at": "2026-12-04T18:00:00+03:00"})
    assert at(later["release_at"]) == at("2026-12-04T18:00:00+03:00")
    # A schedule change before release is nobody's news.
    second = Match.objects.filter(draw__event_id=league["id"]).order_by("round", "position")[1]
    moved = second.scheduled_at + timedelta(hours=2)
    response = staff.post(
        url(cup) + f"order-of-play/matches/{second.id}/move/",
        {"scheduled_at": moved.isoformat(), "note": "Exam"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert all(not change["notify"] for change in ScheduleVersion.objects.first().changes)

    # Play now starts tomorrow: releasing at once is allowed, and every player entered hears once.
    Tournament.objects.filter(pk=cup["id"]).update(
        starts_on=date.today() + timedelta(days=1), ends_on=date.today() + timedelta(days=2)
    )
    out = put(staff, cup, "release/", {"release_at": None})
    assert out["released"] is True
    assert put(staff, cup, "release/", {"release_at": None}, 409)["code"] == "already_released"
    work()
    told = Notification.objects.filter(subject=f"order-of-play:{cup['id']}")
    assert {n.recipient.display_name for n in told} == {"Amina", "Brian", "Chege", "Daudi", "Eli", "Faith"}
    work()
    assert told.count() == 6
    amina = logged_in(person("Amina"))
    seen = order(amina, cup)
    assert seen["released"] and len(seen["slots"]) == 9 and seen["not_before"] == [] and seen["players"] == []
    assert {s["match_id"] for s in seen["slots"] if s["mine"]} == {str(m.id) for m in amina_matches()}
    assert outsider.get(page).json()["scheduled_at"] is not None


def test_stage_order_steers_dispatch_and_falls_through_when_a_stage_is_held_up(staff, club, cup):  # noqa: F811
    league, knockout = cup["events"]
    stages = order(staff, cup)["stages"]
    assert [(s["event_name"], s["stage"], s["placed"]) for s in stages] == [
        ("League", "group", False),
        ("Cup", "knockout", False),
    ]
    # Every stage once, or nothing is saved.
    bad = {"stages": [{"event_id": knockout["id"], "stage": "knockout"}]}
    assert "stages" in put(staff, cup, "stages/", bad, 400)["fields"]
    wanted = [{"event_id": knockout["id"], "stage": "knockout"}, {"event_id": league["id"], "stage": "group"}]
    saved = put(staff, cup, "stages/", {"stages": wanted})["stages"]
    assert [s["label"] for s in saved] == ["Cup, knockout", "League, groups"] and all(
        s["placed"] for s in saved
    )
    logged = MatchDayLog.objects.get(action=MatchDayLog.Action.ORDER_CHANGED)
    assert logged.summary == "Order of play: Cup, knockout, then League, groups" and logged.actor is not None

    start_everything(staff, cup)
    shown = board.build(tournament_of(cup))
    going = [row for row in shown["queue"] if row["suggested_table"]]
    assert [row["event_name"] for row in going] == ["Cup", "Cup"]
    # One semi-final goes out; the other's player is held up, so the free table falls through to the
    # league, with a match whose players are free.
    semis = list(Match.objects.filter(draw__event_id=knockout["id"], round=1).order_by("position"))
    one, _two = tables_of(cup)
    send(staff, {"cup": cup, "event": knockout, "match": semis[0]}, one)
    held_up = next(iter(people(semis[1])))
    NotBefore.objects.create(
        tournament=tournament_of(cup), user_id=held_up, at=datetime.now().astimezone() + timedelta(hours=2)
    )
    shown = board.build(tournament_of(cup))
    rows = {row["match_id"]: row for row in shown["queue"]}
    assert rows[semis[1].id]["state"] == "blocked"
    assert rows[semis[1].id]["reasons"][0]["code"] == "not_before"
    filler = next(row for row in shown["queue"] if row["suggested_table"])
    assert filler["event_name"] == "League" and filler["suggested_table"] == "Table 2"
    busy = people(semis[0]) | {held_up}
    assert not people(Match.objects.get(pk=filler["match_id"])) & busy
    # The control centre counts table use: table 1 has been in use, table 2 idle since play began.
    table_rows = {t["label"]: t for t in shown["tables"]}
    assert table_rows["Table 1"]["use_today"] is not None and table_rows["Table 1"]["idle_since"] is None
    assert table_rows["Table 2"]["idle_since"] is not None and table_rows["Table 2"]["use_today"] == 0

    # Reordered mid-event: the league leads from now on.
    put(staff, cup, "stages/", {"stages": list(reversed(wanted))})
    first = next(row for row in board.build(tournament_of(cup))["queue"] if row["state"] == "ready")
    assert first["event_name"] == "League"
    assert MatchDayLog.objects.filter(action=MatchDayLog.Action.ORDER_CHANGED).count() == 2


def tables_of(cup):  # noqa: F811
    from facilities.models import Table

    return list(Table.objects.filter(venue_id=tournament_of(cup).venue_id).order_by("position"))


def test_a_players_not_before_moves_their_matches_and_holds_them_back(staff, cup):  # noqa: F811
    plan_and_publish(staff, cup)
    release_now(cup)
    amina = person("Amina")
    earliest = min(m.scheduled_at for m in amina_matches())
    eleven = "2026-12-05T11:00:00+03:00"
    assert earliest < at(eleven)
    # Only players entered, and only on the tournament's days.
    stranger = person("Stranger")
    refused = put(staff, cup, f"players/{stranger.id}/", {"at": eleven}, 409)
    assert refused["code"] == "not_entered"
    assert "at" in put(staff, cup, f"players/{amina.id}/", {"at": "2026-12-09T11:00:00+03:00"}, 400)["fields"]

    shown = put(staff, cup, f"players/{amina.id}/", {"at": eleven, "note": "Church in the morning"})
    assert [(row["display_name"], row["note"]) for row in shown["not_before"]] == [
        ("Amina", "Church in the morning")
    ]
    assert all(m.scheduled_at >= at(eleven) for m in amina_matches())
    version = ScheduleVersion.objects.first()
    assert (version.kind, version.reason) == ("moved", "player_request") and version.changes
    assert any(change["notify"] for change in version.changes)  # it is out: people hear
    # Nothing published now breaks a rule, and a fresh recommendation keeps her start too.
    assert staff.get(url(cup) + "schedule/").json()["conflicts"] == []
    again = {
        s["match_id"]: at(s["scheduled_at"]) for s in recommend(staff, cup)["slots"] if s["scheduled_at"]
    }
    assert all(again[str(m.id)] >= at(eleven) for m in amina_matches())
    # A plan that puts her earlier is refused.
    early = min(amina_matches(), key=lambda m: m.scheduled_at)
    clash = [
        {
            "match_id": str(early.id),
            "table_id": str(early.planned_table_id),
            "scheduled_at": "2026-12-05T09:00:00+03:00",
        }
    ]
    refused = keep(staff, cup, clash, 409)
    assert refused["code"] == "schedule_conflicts" and refused["conflicts"][0]["code"] == "player_not_before"
    assert MatchDayLog.objects.filter(action=MatchDayLog.Action.NOT_BEFORE).count() == 1

    # Dispatch holds her match until then, unless staff set it aside with a reason.
    NotBefore.objects.filter(user=amina).update(at=datetime.now().astimezone() + timedelta(hours=1))
    start_everything(staff, cup)
    match = next(m for m in amina_matches() if m.entry_a_id and m.entry_b_id and m.round == 1)
    event = next(e for e in cup["events"] if e["id"] == str(match.draw.event_id))
    game = {"cup": cup, "event": event, "match": match}
    one = tables_of(cup)[0]
    assert send(staff, game, one, 409)["code"] == "not_before"
    send(staff, game, one, overrides=["not_before"], reason="She arrived early")

    cleared = staff.delete(url(cup) + f"order-of-play/players/{amina.id}/")
    assert cleared.status_code == 200 and cleared.json()["not_before"] == []
    assert staff.delete(url(cup) + f"order-of-play/players/{amina.id}/").status_code == 404


def test_moving_one_match_later_publishes_it_and_what_follows(staff, cup):  # noqa: F811
    league = cup["events"][0]
    first = Match.objects.filter(draw__event_id=league["id"]).order_by("round", "position").first()
    path = url(cup) + f"order-of-play/matches/{first.id}/move/"
    assert staff.post(path, {"scheduled_at": "2026-12-05T11:00:00+03:00"}, format="json").json()["code"] == (
        "not_published"
    )
    plan_and_publish(staff, cup)
    first.refresh_from_db()
    before = first.scheduled_at
    assert staff.post(path, {"scheduled_at": before.isoformat()}, format="json").status_code == 400
    later = before + timedelta(minutes=95)
    outsider = logged_in(person("Onlooker"))
    assert outsider.post(path, {"scheduled_at": later.isoformat()}, format="json").status_code == 403
    response = staff.post(
        path, {"scheduled_at": later.isoformat(), "reason": "other", "note": "Bus late"}, format="json"
    )
    assert response.status_code == 200, response.json()
    first.refresh_from_db()
    # No earlier than asked; later still if one of its players is busy then.
    assert first.scheduled_at >= later and first.draft_at == first.scheduled_at
    version = ScheduleVersion.objects.first()
    assert (version.kind, version.reason, version.note) == ("moved", "other", "Bus late")
    assert MatchDayLog.objects.filter(action=MatchDayLog.Action.MATCH_MOVED, match=first).exists()
    # Whatever then clashed with it moved on too; the published schedule has no conflicts.
    assert staff.get(url(cup) + "schedule/").json()["conflicts"] == []


def test_only_the_hosts_competition_staff_manage_the_order_of_play(staff, cup):  # noqa: F811
    plan_and_publish(staff, cup)
    league = cup["events"][0]
    match = Match.objects.filter(draw__event_id=league["id"]).first()
    amina = person("Amina")
    outsider = logged_in(person("Onlooker"))
    stages = {"stages": [{"event_id": e["id"], "stage": "group"} for e in cup["events"]]}
    assert outsider.put(url(cup) + "order-of-play/stages/", stages, format="json").status_code == 403
    assert (
        outsider.put(url(cup) + "order-of-play/release/", {"release_at": None}, format="json").status_code
        == 403
    )
    body = {"at": "2026-12-05T11:00:00+03:00"}
    assert (
        outsider.put(url(cup) + f"order-of-play/players/{amina.id}/", body, format="json").status_code == 403
    )
    assert outsider.delete(url(cup) + f"order-of-play/players/{amina.id}/").status_code == 403
    move = {"scheduled_at": "2026-12-05T15:00:00+03:00"}
    assert (
        outsider.post(url(cup) + f"order-of-play/matches/{match.id}/move/", move, format="json").status_code
        == 403
    )
    assert not NotBefore.objects.exists()
