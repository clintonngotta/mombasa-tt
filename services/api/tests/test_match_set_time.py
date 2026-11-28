"""Setting one match's table and start by hand, published at once, without the working plan (TASK-149).
For organizers who schedule match by match: only conflicts the change itself makes stop it."""

import pytest
from django.core import mail

from competitions.models import Match, MatchDayLog, ScheduleVersion

from .helpers import logged_in, make_user
from .test_ratings import work
from .test_schedule import cup, drawn, hall, people, schedule  # noqa: F401
from .test_schedule_publication import league, released
from .test_tournaments import url

pytestmark = pytest.mark.django_db

UNKNOWN = "7d1b8c5e-0000-4000-8000-000000000000"


def set_time(client, cup, match_id, table, when, expect=200, **extra) -> dict:  # noqa: F811
    body = {"table_id": table, "scheduled_at": when and f"2026-12-05T{when}:00+03:00", **extra}
    response = client.post(url(cup) + f"schedule/matches/{match_id}/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_a_match_is_given_a_table_and_start_and_published_at_once(staff, cup):  # noqa: F811
    one = schedule(staff, cup)["tables"][0]["id"]
    first = league(1)[0]

    done = set_time(staff, cup, first.id, one, "09:00", note="By hand")
    version = done["version"]
    assert (version["number"], version["kind"], version["note"]) == (1, "set", "By hand")
    first.refresh_from_db()
    assert (
        str(first.planned_table_id) == one and first.scheduled_at.hour == 6
    )  # 09:00 in Nairobi is 06:00 UTC
    # The working plan follows, so publishing the plan later doesn't undo it.
    assert (first.draft_table_id, first.draft_at) == (first.planned_table_id, first.scheduled_at)
    assert MatchDayLog.objects.filter(action="match_timed", match=first).exists()
    assert done["warnings"] == []  # no sessions were set, and none are needed
    assert set_time(staff, cup, first.id, one, "09:00", 409)["code"] == "nothing_to_publish"

    # A time without a table, then taking the time away.
    set_time(staff, cup, first.id, None, "11:00")
    set_time(staff, cup, first.id, None, None)
    first.refresh_from_db()
    assert first.scheduled_at is None and ScheduleVersion.objects.count() == 3


def test_only_conflicts_the_change_makes_stop_it(staff, cup):  # noqa: F811
    one, two = (t["id"] for t in schedule(staff, cup)["tables"])
    b, c = league(1)
    later = next(m for m in league(2) if people(m) & people(b))

    set_time(staff, cup, b.id, one, "09:00")
    assert [x["code"] for x in set_time(staff, cup, c.id, one, "09:10", 409)["conflicts"]] == ["table_taken"]
    assert [x["code"] for x in set_time(staff, cup, later.id, two, "09:10", 409)["conflicts"]] == [
        "player_busy"
    ]
    outside = "2026-12-09T09:00:00+03:00"
    response = staff.post(
        url(cup) + f"schedule/matches/{c.id}/", {"table_id": two, "scheduled_at": outside}, format="json"
    )
    assert response.status_code == 409 and response.json()["conflicts"][0]["code"] == "outside_dates"
    assert Match.objects.get(pk=c.pk).scheduled_at is None, "nothing is published when refused"

    # A clash already in the published schedule doesn't block an unrelated change.
    b.refresh_from_db()
    Match.objects.filter(pk=c.pk).update(planned_table_id=one, scheduled_at=b.scheduled_at)
    assert set_time(staff, cup, later.id, two, "11:00")["version"]["kind"] == "set"


def test_players_are_told_when_a_published_time_changes(staff, cup):  # noqa: F811
    one = schedule(staff, cup)["tables"][0]["id"]
    b = league(1)[0]
    set_time(staff, cup, b.id, one, "09:00")
    released(cup)
    mail.outbox.clear()
    moved = set_time(staff, cup, b.id, one, "10:00")
    assert [change["notify"] for change in moved["version"]["changes"]] == [True]
    work()
    wanted = {p.user.email for e in (b.entry_a, b.entry_b) for p in e.players.all()}
    assert {message.to[0] for message in mail.outbox} == wanted


def test_outside_a_session_warns_and_only_staff_set_plannable_matches(staff, cup):  # noqa: F811
    one, two = (t["id"] for t in schedule(staff, cup)["tables"])
    made = staff.post(
        url(cup) + "schedule/sessions/",
        {"day": "2026-12-05", "starts": "09:00", "ends": "12:00", "table_ids": [one]},
        format="json",
    )
    assert made.status_code == 201, made.json()
    b = league(1)[0]
    assert [w["code"] for w in set_time(staff, cup, b.id, two, "15:00")["warnings"]] == ["outside_session"]

    assert "table_id" in set_time(staff, cup, b.id, UNKNOWN, "16:00", 400)["fields"]
    assert set_time(staff, cup, UNKNOWN, one, "09:00", 409)["code"] == "not_plannable"
    stranger = logged_in(make_user("stranger@example.com"))
    response = stranger.post(
        url(cup) + f"schedule/matches/{b.id}/", {"table_id": one, "scheduled_at": None}, format="json"
    )
    assert response.status_code in (403, 404)
    b.refresh_from_db()
    assert str(b.planned_table_id) == two
