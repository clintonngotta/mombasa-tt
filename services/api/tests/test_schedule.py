"""The recommended day schedule and its checks (TASK-099)."""

from datetime import datetime, timedelta

import pytest

from competitions.models import Entry, Match
from reservations import board

from .helpers import logged_in
from .test_draws import draw_url
from .test_entries import enter
from .test_reservations import person
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


def drawn(staff, tournament, event, names):
    for players in names:
        enter(staff, tournament, event, player_ids=[str(person(name).id) for name in players])
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200


@pytest.fixture
def cup(staff, club, hall):
    """A round robin of four and a knockout of four that shares Amina and Brian, both drawn."""
    tournament = make_tournament(staff, club, hall)
    add_event(staff, tournament, name="League", format="round_robin")
    add_event(staff, tournament, name="Cup", format="knockout", seeding="none")
    tournament = do(staff, tournament, "publish")
    league, knockout = tournament["events"]
    drawn(staff, tournament, league, [["Amina"], ["Brian"], ["Chege"], ["Daudi"]])
    drawn(staff, tournament, knockout, [["Amina"], ["Brian"], ["Eli"], ["Faith"]])
    return tournament


def schedule(client, cup, expect=200) -> dict:
    response = client.get(url(cup) + "schedule/")
    assert response.status_code == expect, response.json()
    return response.json()


def recommend(client, cup, expect=200, **body) -> dict:
    response = client.post(url(cup) + "schedule/recommend/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def keep(client, cup, slots, expect=200) -> dict:
    response = client.put(url(cup) + "schedule/", {"slots": slots}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def at(value) -> datetime:
    return datetime.fromisoformat(value)


def people(match: Match) -> set:
    return {
        place.user_id for entry in (match.entry_a, match.entry_b) if entry for place in entry.players.all()
    }


def test_the_recommendation_keeps_tables_players_and_rounds_apart(staff, cup):
    shown = schedule(staff, cup)
    assert [t["label"] for t in shown["tables"]] == ["Table 1", "Table 2"]
    assert len(shown["rows"]) == 6 + 3 and all(row["scheduled_at"] is None for row in shown["rows"])

    made = recommend(staff, cup)
    assert made["conflicts"] == [] and made["warnings"] == []
    slots = made["slots"]
    assert len(slots) == 9 and not any(slot["beyond_last_day"] for slot in slots)
    # The first day opens at nine in the tournament's time zone, and everything lands in steps.
    assert min(at(s["scheduled_at"]) for s in slots) == at("2026-12-05T09:00:00+03:00")

    matches = {str(m.id): m for m in Match.objects.prefetch_related("entry_a__players", "entry_b__players")}
    length, rest = timedelta(minutes=30), timedelta(minutes=10)
    placed = sorted(((at(s["scheduled_at"]), s) for s in slots), key=lambda pair: pair[0])
    for index, (start, slot) in enumerate(placed):
        for other_start, other in placed[index + 1 :]:
            if other_start < start + length:
                assert other["table_id"] != slot["table_id"]
            if other_start < start + length + rest:
                assert not people(matches[slot["match_id"]]) & people(matches[other["match_id"]])
    final = next(m for m in matches.values() if m.draw.event.name == "Cup" and m.round == 2)
    semis = [m for m in matches.values() if final.feeder_a_id == m.id or final.feeder_b_id == m.id]
    starts = {s["match_id"]: at(s["scheduled_at"]) for s in slots}
    assert starts[str(final.id)] >= max(starts[str(m.id)] for m in semis) + length + rest

    # Nothing was kept until the organizers keep it.
    assert all(row["scheduled_at"] is None for row in schedule(staff, cup)["rows"])
    kept = keep(staff, cup, [{k: s[k] for k in ("match_id", "table_id", "scheduled_at")} for s in slots])
    assert kept["conflicts"] == []
    assert {row["match_id"]: at(row["scheduled_at"]) for row in kept["rows"]} == starts
    shown = staff.get(url(cup, event=cup["events"][1]) + f"matches/{final.id}/").json()
    assert shown["table"] in {"Table 1", "Table 2"} and at(shown["scheduled_at"]) == starts[str(final.id)]


def test_the_recommendation_uses_only_the_tables_and_hours_chosen(staff, cup):
    tables = schedule(staff, cup)["tables"]
    made = recommend(staff, cup, table_ids=[tables[1]["id"]], day_starts="10:00", day_ends="12:00")
    slots = made["slots"]
    assert {s["table_id"] for s in slots} == {tables[1]["id"]}
    nairobi = at("2026-12-05T00:00:00+03:00").tzinfo
    starts = sorted(at(s["scheduled_at"]).astimezone(nairobi) for s in slots)
    assert starts[0] == at("2026-12-05T10:00:00+03:00")
    # Every match starts and ends within the hours chosen, so nine matches need more than the two days.
    for start in starts:
        assert start.hour >= 10 and (start + timedelta(minutes=30)).time() <= at("2026-12-05T12:00:00").time()
    for slot in slots:
        late = at(slot["scheduled_at"]).astimezone(nairobi).date().isoformat() > "2026-12-06"
        assert slot["beyond_last_day"] is late
    assert any(slot["beyond_last_day"] for slot in slots)
    assert recommend(staff, cup, 400, day_starts="12:00", day_ends="10:00")["fields"]["day_ends"]


def test_edits_that_cannot_work_are_refused_with_every_conflict(staff, cup):
    tables = schedule(staff, cup)["tables"]
    one, two = tables[0]["id"], tables[1]["id"]
    league = list(Match.objects.filter(draw__event__name="League").order_by("round", "position"))
    knockout = list(Match.objects.filter(draw__event__name="Cup").order_by("round", "position"))
    nine = "2026-12-05T09:00:00+03:00"
    first, second = league[0], league[1]  # round 1: four different players

    def slot(match, table, when):
        return {"match_id": str(match.id), "table_id": table, "scheduled_at": when}

    refused = keep(staff, cup, [slot(first, one, nine), slot(second, one, nine)], expect=409)
    assert refused["code"] == "schedule_conflicts"
    assert [c["code"] for c in refused["conflicts"]] == ["table_taken"]

    # Somebody in two matches at once, or without their rest.
    amina = person("Amina").id
    mine = [m for m in league if amina in people(m)]
    refused = keep(
        staff, cup, [slot(mine[0], one, nine), slot(mine[1], two, "2026-12-05T09:35:00+03:00")], expect=409
    )
    assert [c["code"] for c in refused["conflicts"]] == ["player_busy"]
    assert "Amina" in refused["message"] and "rest" in refused["message"]

    # The final before its semi-finals, and a day the tournament doesn't have.
    semi, final = knockout[0], knockout[-1]
    refused = keep(
        staff,
        cup,
        [slot(semi, one, "2026-12-05T10:00:00+03:00"), slot(final, two, "2026-12-05T10:15:00+03:00")],
        expect=409,
    )
    assert [c["code"] for c in refused["conflicts"]] == ["before_earlier_match"]
    assert keep(staff, cup, [slot(first, one, "2026-12-09T10:00:00+03:00")], 409)["conflicts"][0]["code"] == (
        "outside_dates"
    )

    # The check says the same without keeping anything; a sound plan is kept.
    checked = staff.post(
        url(cup) + "schedule/check/",
        {"slots": [slot(first, one, nine), slot(second, one, nine)]},
        format="json",
    ).json()
    assert [c["code"] for c in checked["conflicts"]] == ["table_taken"]
    assert Match.objects.filter(scheduled_at__isnull=False).count() == 0
    keep(staff, cup, [slot(first, one, nine), slot(second, two, nine)])
    assert Match.objects.filter(scheduled_at__isnull=False).count() == 2


def test_a_possible_player_is_a_warning_not_a_conflict(staff, cup):
    tables = schedule(staff, cup)["tables"]
    cup_matches = list(Match.objects.filter(draw__event__name="Cup").order_by("round", "position"))
    final = cup_matches[-1]
    semis = cup_matches[:2]
    amina_league = next(
        m for m in Match.objects.filter(draw__event__name="League") if person("Amina").id in people(m)
    )
    one, two = tables[0]["id"], tables[1]["id"]
    planned = [
        (semis[0], one, "09:00"),
        (semis[1], two, "09:00"),
        (final, one, "10:00"),
        (amina_league, two, "10:00"),
    ]
    slots = [
        {"match_id": str(m.id), "table_id": t, "scheduled_at": f"2026-12-05T{when}:00+03:00"}
        for m, t, when in planned
    ]
    kept = keep(staff, cup, slots)
    assert kept["conflicts"] == []
    # Amina may reach the final from her semi-final while her league match is on.
    assert kept["warnings"] and {w["code"] for w in kept["warnings"]} == {"player_may_be_busy"}
    assert {w["match_id"] for w in kept["warnings"]} <= {str(final.id), str(amina_league.id)}


def test_the_schedule_is_for_staff_and_the_board_offers_the_planned_table(staff, club, cup):
    outsider = logged_in(person("Onlooker"))
    assert schedule(outsider, cup, 403)["code"] == "permission_denied"
    assert recommend(outsider, cup, 403)["code"] == "permission_denied"
    assert keep(outsider, cup, [], 403)["code"] == "permission_denied"

    tables = schedule(staff, cup)["tables"]
    first = Match.objects.filter(draw__event__name="League").order_by("round", "position").first()
    # A planned start puts it first in the queue.
    planned = {
        "match_id": str(first.id),
        "table_id": tables[1]["id"],
        "scheduled_at": "2026-12-05T09:00:00+03:00",
    }
    keep(staff, cup, [planned])
    league = cup["events"][0]
    for entry in Entry.objects.filter(event_id=league["id"]):
        staff.post(url(cup, event=league) + f"entries/{entry.id}/check-in/", {}, format="json")
    do(staff, cup, "start")
    do(staff, cup, "start", event=league)
    shown = board.build(first.draw.event.tournament)
    row = next(r for r in shown["queue"] if r["match_id"] == first.id)
    assert row["suggested_table"] == "Table 2", (row["state"], row["reasons"])
