"""Sessions, published schedule versions with notices, reservations and table delays (TASK-081)."""

from datetime import datetime, timedelta

import pytest
from django.core import mail
from django.utils import timezone

from competitions.models import Entry, Match, ScheduleVersion, Tournament
from reservations import service as reservations
from scoring.models import Scorecard

from .helpers import logged_in
from .test_ratings import work
from .test_reservations import person
from .test_schedule import at, cup, drawn, hall, keep, people, publish, recommend, schedule  # noqa: F401
from .test_tournaments import do, url

pytestmark = pytest.mark.django_db


def league(round_number: int) -> list[Match]:
    return list(
        Match.objects.filter(draw__event__name="League", round=round_number)
        .order_by("position")
        .prefetch_related("entry_a__players", "entry_b__players")
    )


def slot(match, table, when: str) -> dict:
    return {"match_id": str(match.id), "table_id": table, "scheduled_at": f"2026-12-05T{when}:00+03:00"}


def session(client, cup, expect=201, **body) -> dict:  # noqa: F811
    response = client.post(url(cup) + "schedule/sessions/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def released(cup) -> None:  # noqa: F811
    """The order of play is out (REQ-053): from now on a change is news for the people it moves."""
    Tournament.objects.filter(pk=cup["id"]).update(order_of_play_release_at=timezone.now())


def emails_to() -> dict:
    return {message.to[0]: message.body for message in mail.outbox}


def test_sessions_hold_the_recommendation_to_their_hours_tables_and_events(staff, cup):  # noqa: F811
    tables = schedule(staff, cup)["tables"]
    one, two = tables[0]["id"], tables[1]["id"]
    league_event, cup_event = cup["events"]
    morning = session(
        staff,
        cup,
        day="2026-12-05",
        starts="10:00",
        ends="12:00",
        table_ids=[two],
        event_ids=[league_event["id"]],
    )
    session(staff, cup, name="Cup", day="2026-12-06", starts="14:00", ends="16:00", table_ids=[one])
    assert [s["starts"] for s in schedule(staff, cup)["sessions"]] == ["10:00:00", "14:00:00"]

    slots = {s["match_id"]: s for s in recommend(staff, cup)["slots"]}
    morning_hours = (at("2026-12-05T10:00:00+03:00"), at("2026-12-05T11:30:00+03:00"))
    afternoon = (at("2026-12-06T14:00:00+03:00"), at("2026-12-06T15:30:00+03:00"))
    for match in Match.objects.filter(draw__event__name__in=["League", "Cup"]):
        placed = slots[str(match.id)]
        if not placed["table_id"]:
            continue
        start = at(placed["scheduled_at"])
        # The morning is the league's alone, on Table 2; the afternoon is open to every event.
        if placed["table_id"] == two:
            assert match.draw.event.name == "League" and morning_hours[0] <= start <= morning_hours[1]
        else:
            assert placed["table_id"] == one and afternoon[0] <= start <= afternoon[1]
    unplaced = [s for s in slots.values() if s["table_id"] is None]
    assert all(s["scheduled_at"] is None for s in unplaced)

    # A plan outside every session is allowed, with a warning.
    first = league(1)[0]
    kept = keep(staff, cup, [slot(first, one, "09:00")])
    assert {w["code"] for w in kept["warnings"]} == {"outside_session"}

    bad = [
        ({"day": "2026-12-09", "starts": "09:00", "ends": "10:00", "table_ids": [one]}, "day"),
        ({"day": "2026-12-05", "starts": "11:00", "ends": "10:00", "table_ids": [one]}, "ends"),
        ({"day": "2026-12-05", "starts": "09:00", "ends": "10:00", "table_ids": []}, "table_ids"),
    ]
    for body, field in bad:
        assert field in session(staff, cup, 400, **body)["fields"]
    changed = staff.patch(
        url(cup) + f"schedule/sessions/{morning['id']}/", {"name": "Morning"}, format="json"
    ).json()
    assert changed["name"] == "Morning"
    assert staff.delete(url(cup) + f"schedule/sessions/{morning['id']}/").status_code == 204
    outsider = logged_in(person("Onlooker"))
    assert outsider.get(url(cup) + "schedule/sessions/").status_code == 403


def test_publishing_keeps_versions_and_tells_only_the_people_whose_matches_moved(staff, cup):  # noqa: F811
    tables = schedule(staff, cup)["tables"]
    one, two = tables[0]["id"], tables[1]["id"]
    b, c = league(1)
    a = next(m for m in league(2) if people(m) & people(b))
    umpire = person("Umpire Uma")
    Scorecard.objects.create(match=c, umpire=umpire)

    mail.outbox.clear()  # the entries' own news
    keep(staff, cup, [slot(b, one, "09:00"), slot(c, two, "09:00"), slot(a, one, "10:00")])
    first = publish(staff, cup, note="First plan")
    released(cup)  # before the order of play is out, a change is nobody's news (REQ-053)
    assert (first["number"], first["kind"], first["change_count"], first["notify_count"]) == (
        1,
        "published",
        3,
        0,
    )
    work()
    assert mail.outbox == []  # times nobody had before are not changes
    assert publish(staff, cup, 409)["code"] == "nothing_to_publish"

    # A: ten minutes, under the threshold. B: half an hour. C: another table.
    keep(staff, cup, [slot(a, one, "10:10"), slot(b, one, "09:30"), slot(c, one, "09:00")])
    second = publish(staff, cup)
    assert second["number"] == 2 and second["change_count"] == 3
    told = {change["match_id"] for change in second["changes"] if change["notify"]}
    assert told == {str(b.id), str(c.id)}
    work()
    wanted = {
        u.email for m in (b, c) for e in (m.entry_a, m.entry_b) for u in [p.user for p in e.players.all()]
    }
    assert set(emails_to()) == wanted | {umpire.email}
    assert all("round 2" not in body and "estimates only" in body for body in emails_to().values())
    assert "09:30" in next(
        body for to, body in emails_to().items() if to in {p.user.email for p in b.entry_a.players.all()}
    )
    work()
    assert len(mail.outbox) == len(wanted) + 1  # the job is done once
    assert ScheduleVersion.objects.get(number=2).notified_count == len(wanted) + 1

    # History: both versions, the first as it was.
    listed = staff.get(url(cup) + "schedule/versions/").json()
    assert [v["number"] for v in listed] == [2, 1]
    old = staff.get(url(cup) + "schedule/versions/1/").json()
    assert {s["match_id"]: at(s["scheduled_at"]) for s in old["slots"]}[str(b.id)] == at(
        "2026-12-05T09:00:00+03:00"
    )
    assert schedule(staff, cup)["published_version"] == 2

    # A plan with conflicts is never published.
    Match.objects.filter(pk=c.pk).update(draft_at=datetime.fromisoformat("2026-12-05T09:40:00+03:00"))
    refused = publish(staff, cup, 409)
    assert refused["code"] == "schedule_conflicts" and refused["conflicts"]
    outsider = logged_in(person("Onlooker"))
    assert outsider.post(url(cup) + "schedule/publish/", {}, format="json").status_code == 403


def test_plans_are_checked_against_matches_on_tables_now(staff, cup):  # noqa: F811
    tables = schedule(staff, cup)["tables"]
    one, two = tables[0]["id"], tables[1]["id"]
    league_event = cup["events"][0]
    for entry in Entry.objects.filter(event_id=league_event["id"]):
        staff.post(url(cup, event=league_event) + f"entries/{entry.id}/check-in/", {}, format="json")
    do(staff, cup, "start")
    do(staff, cup, "start", event=league_event)
    playing, other = league(1)
    from facilities.models import Table

    reservations.dispatch(playing, Table.objects.get(pk=one), None)
    soon = (timezone.now() + timedelta(minutes=5)).isoformat()
    later = next(m for m in league(2) if people(m) & people(playing))
    checked = staff.post(
        url(cup) + "schedule/check/",
        {
            "slots": [
                {"match_id": str(other.id), "table_id": one, "scheduled_at": soon},
                {"match_id": str(later.id), "table_id": two, "scheduled_at": soon},
            ]
        },
        format="json",
    ).json()
    codes = {(c["match_id"], c["code"]) for c in checked["conflicts"]}
    assert (str(other.id), "table_in_use") in codes
    assert (str(later.id), "player_on_table") in codes
    # The recommendation keeps clear of them too.
    slots = {s["match_id"]: s for s in recommend(staff, cup)["slots"]}
    assert str(playing.id) not in slots


def test_a_table_delay_moves_its_matches_and_what_clashes_with_them(staff, cup):  # noqa: F811
    tables = schedule(staff, cup)["tables"]
    one, two = tables[0]["id"], tables[1]["id"]
    b, c = league(1)
    a = next(m for m in league(2) if people(m) & people(b))
    keep(staff, cup, [slot(b, one, "09:00"), slot(c, two, "09:00"), slot(a, two, "09:40")])
    publish(staff, cup)
    released(cup)
    nothing = staff.post(
        url(cup) + "schedule/delay/", {"table_id": two, "minutes": 5, "reason": "other"}, format="json"
    )
    assert nothing.status_code == 200  # Table 2 has C and A

    done = staff.post(
        url(cup) + "schedule/delay/",
        {"table_id": one, "minutes": 30, "reason": "late_start", "note": "Lights"},
        format="json",
    ).json()
    version = done["version"]
    assert (version["kind"], version["reason"], version["delay_minutes"]) == ("delay", "late_start", 30)
    assert version["delayed_table"]["id"] == one
    starts = {m.id: m.scheduled_at for m in Match.objects.filter(pk__in=[a.id, b.id, c.id])}
    assert starts[b.id] == at("2026-12-05T09:30:00+03:00")
    # A shares a player with B: it waits for B to end at 10:00 and the ten minutes' rest.
    assert starts[a.id] == at("2026-12-05T10:10:00+03:00")
    assert starts[c.id] == at("2026-12-05T09:05:00+03:00")
    assert done["conflicts"] == []
    assert {ch["match_id"] for ch in version["changes"]} == {str(a.id), str(b.id)}
    assert all(ch["notify"] for ch in version["changes"])
    # The working plan follows, so the next publication doesn't undo the delay.
    assert Match.objects.get(pk=a.pk).draft_at == starts[a.id]
    assert [v["number"] for v in staff.get(url(cup) + "schedule/versions/").json()] == [3, 2, 1]
    work()
    assert mail.outbox

    empty = Match.objects.filter(draw__event__name="Cup").first()
    assert empty.planned_table is None
    from facilities.models import Table

    spare = Table.objects.create(venue_id=cup["venue"]["id"], label="Table 3", position=5)
    refused = staff.post(
        url(cup) + "schedule/delay/",
        {"table_id": str(spare.id), "minutes": 10, "reason": "other"},
        format="json",
    )
    assert refused.status_code == 409 and refused.json()["code"] == "nothing_planned"
