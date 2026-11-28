"""Recommending a schedule within the day's hours on every day of the tournament (TASK-150): the
organizers give a start and an end, and the plan fills the first day before the next. Sessions, when
there are any, can be set aside for this."""

from datetime import timedelta

import pytest

from .test_schedule import at, cup, drawn, hall, recommend, schedule  # noqa: F401
from .test_tournaments import url

pytestmark = pytest.mark.django_db

NAIROBI = at("2026-12-05T00:00:00+03:00").tzinfo


def local(value):
    return at(value).astimezone(NAIROBI)


def test_the_days_hours_fill_the_first_day_before_the_next(staff, cup):  # noqa: F811
    made = recommend(staff, cup, day_starts="09:00", day_ends="21:00", use_sessions=False)
    slots = made["slots"]
    assert all(slot["scheduled_at"] and slot["table_id"] for slot in slots), "every match is placed"
    assert {local(slot["scheduled_at"]).date().isoformat() for slot in slots} == {"2026-12-05"}
    first, second = made["days"]
    assert (first["day"], first["matches"], second["day"], second["matches"]) == (
        "2026-12-05",
        len(slots),
        "2026-12-06",
        0,
    )
    assert local(first["first_start"]).hour == 9 and local(first["last_end"]).hour < 21


def test_what_doesnt_fit_the_days_is_flagged_and_left_out_of_them(staff, cup):  # noqa: F811
    one = schedule(staff, cup)["tables"][0]["id"]
    made = recommend(staff, cup, table_ids=[one], day_starts="09:00", day_ends="10:00", use_sessions=False)
    slots = made["slots"]
    within = [s for s in slots if not s["beyond_last_day"]]
    beyond = [s for s in slots if s["beyond_last_day"]]
    assert within and beyond and all(s["scheduled_at"] for s in beyond)
    assert sum(day["matches"] for day in made["days"]) == len(within)
    for slot in within:
        start = local(slot["scheduled_at"])
        assert start.hour == 9 and start + timedelta(minutes=30) <= start.replace(hour=10, minute=0)


def test_sessions_can_be_set_aside_for_the_days_hours(staff, cup):  # noqa: F811
    one = schedule(staff, cup)["tables"][0]["id"]
    made = staff.post(
        url(cup) + "schedule/sessions/",
        {"day": "2026-12-05", "starts": "09:00", "ends": "10:00", "table_ids": [one]},
        format="json",
    )
    assert made.status_code == 201, made.json()
    # Inside the one short session, most matches find no place.
    in_sessions = recommend(staff, cup)["slots"]
    assert any(slot["scheduled_at"] is None for slot in in_sessions)
    # Within the day's hours instead, every match is placed on the tournament's days.
    by_hours = recommend(staff, cup, day_starts="09:00", day_ends="21:00", use_sessions=False)["slots"]
    assert all(slot["scheduled_at"] and not slot["beyond_last_day"] for slot in by_hours)
