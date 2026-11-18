"""Official results, the work that follows from them and corrections (REQ-015, EVAL-015, TASK-029)."""

from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from competitions import drawing, lifecycle, official
from competitions.models import Event, Match, OfficialResult, Resolution
from core.exceptions import ApiException
from outbox import service as outbox
from outbox.models import Job
from reservations import service as reservations
from reservations.models import Hold, Reservation
from scoring.models import Scorecard, ScoreEvent

from .test_reservations import send, started, tables
from .test_tournaments import url
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db

GAMES = [[11, 5], [11, 7], [11, 9]]
LOST = [[5, 11], [7, 11], [9, 11]]


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


def knockout(staff, club, hall, **event) -> dict:
    """Four players: two semi-finals and a final."""
    game = started(staff, club, hall, [["Amina"], ["Brian"], ["Chege"], ["Daudi"]], **event)
    matches = Match.objects.filter(draw__event_id=game["event"]["id"])
    game["semis"] = list(matches.filter(round=1).order_by("position"))
    game["final"] = matches.get(round=2)
    return game


def post(client, game, match, action, expect=200, **body) -> dict:
    path = url(game["cup"], event=game["event"]) + f"matches/{match.id}/{action}/"
    response = client.post(path, body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def enter(client, game, match, winner, expect=200, **body) -> dict:
    return post(client, game, match, "result", expect, winner_entry_id=str(winner.id), **body)


def correct(
    client, game, match, winner, expect=200, reason="Sides were swapped on the sheet", **body
) -> dict:
    return post(
        client, game, match, "result/correct", expect, winner_entry_id=str(winner.id), reason=reason, **body
    )


def fresh(match: Match) -> Match:
    return Match.objects.select_related("entry_a", "entry_b", "winner").get(pk=match.pk)


def code_of(raised) -> str:
    return raised.value.get_codes()


def test_a_result_is_written_once_with_its_history_and_the_work_that_follows(staff, club, hall):
    game = knockout(staff, club, hall)
    one, _ = tables(hall)
    semi = game["semis"][0]
    send(staff, {**game, "match": semi}, one)
    shown = enter(staff, game, semi, semi.entry_a, games=GAMES)
    assert shown["status"] == "completed" and shown["on_table"] is None
    result = shown["result"]
    assert (result["version"], result["source"], result["winner"], result["games"]) == (
        1,
        "staff",
        official.title(semi.entry_a),
        GAMES,
    )
    assert result["recorded_by"] and result["processing"] is True
    # In the same transaction: the table and players are free and the winner is in the final.
    assert not Hold.objects.filter(active=True).exists()
    assert semi.entry_a_id in (fresh(game["final"]).entry_a_id, fresh(game["final"]).entry_b_id)
    # The same entry sent again (its first answer was lost) changes nothing and succeeds.
    assert enter(staff, game, semi, semi.entry_a, games=GAMES)["result"]["version"] == 1
    # Entering something else is refused: nothing progresses twice.
    assert enter(staff, game, semi, semi.entry_b, expect=409, games=LOST)["code"] == "match_decided"
    assert OfficialResult.objects.filter(match=semi).count() == 1
    assert Job.objects.filter(kind="result.project").count() == 1


def test_the_work_after_a_result_survives_a_failing_worker_and_a_replay(staff, club, hall, monkeypatch):
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    seen = []

    def failing(result):
        seen.append(result.id)
        raise RuntimeError("the worker was interrupted")

    monkeypatch.setattr(official, "PROJECTIONS", [failing])
    assert outbox.work() == 1
    job = Job.objects.get()
    assert (job.status, job.attempts) == ("pending", 1) and "interrupted" in job.last_error
    assert OfficialResult.objects.get().projected_at is None  # still shown as processing
    assert outbox.work() == 0  # not due again yet: it backs off

    monkeypatch.setattr(official, "PROJECTIONS", [lambda result: seen.append(result.id)])
    Job.objects.update(available_at=timezone.now())
    assert outbox.work() == 1
    job.refresh_from_db()
    assert (job.status, job.attempts, job.last_error) == ("done", 2, "")
    assert OfficialResult.objects.get().projected_at is not None
    assert outbox.work() == 0 and len(seen) == 2  # done once; nothing left to do
    # The same job written again is the same job, and replaying it converges on the same state.
    assert outbox.enqueue("result.project", job.key, job.payload).id == job.id
    Job.objects.update(status="pending")
    assert outbox.work() == 1 and OfficialResult.objects.count() == 1
    shown = staff.get(url(game["cup"], event=game["event"]) + f"matches/{semi.id}/").json()
    assert shown["result"]["processing"] is False


def test_a_result_that_cannot_release_its_table_is_not_recorded_at_all(staff, club, hall, monkeypatch):
    game = knockout(staff, club, hall)
    one, _ = tables(hall)
    semi = game["semis"][0]
    send(staff, {**game, "match": semi}, one)

    def broken(*args, **kwargs):
        raise RuntimeError("release failed")

    monkeypatch.setattr(reservations, "release", broken)
    with pytest.raises(RuntimeError), transaction.atomic():
        drawing.record_result(semi, semi.entry_a, games=GAMES)
    assert fresh(semi).status == "scheduled"
    assert Hold.objects.filter(active=True).count() == 3 and Reservation.objects.get().status == "active"
    assert not OfficialResult.objects.exists() and not Job.objects.exists()
    assert fresh(game["final"]).entry_a_id is None and fresh(game["final"]).entry_b_id is None


def test_a_correction_keeps_the_earlier_result_with_its_author_and_reason(staff, club, hall):
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    assert correct(staff, game, semi, semi.entry_a, expect=400, reason="", games=GAMES)["fields"]["reason"]
    assert correct(staff, game, semi, semi.entry_a, expect=409, games=GAMES)["code"] == "nothing_to_correct"
    better = [[11, 5], [9, 11], [11, 7], [11, 9]]
    shown = correct(staff, game, semi, semi.entry_a, games=better, reason="Second game was missed")
    assert (shown["result"]["version"], shown["games"]) == (2, better)
    first, second = shown["result_history"]
    assert (first["version"], first["current"], first["games"]) == (1, False, GAMES)
    assert (second["source"], second["reason"], second["current"]) == (
        "correction",
        "Second game was missed",
        True,
    )
    assert second["recorded_by"] == first["recorded_by"] != ""
    kept = OfficialResult.objects.order_by("version")
    assert kept[0].first_accepted_at == kept[1].first_accepted_at  # its place in the order of results
    # Games that don't fit the outcome are refused, and a player only sees the result that stands.
    assert correct(staff, game, semi, semi.entry_b, expect=400, games=better)["code"] == "invalid_result"
    assert Resolution.objects.count() == 0 and Event.objects.get(pk=game["event"]["id"]).paused_at is None


def test_a_changed_winner_takes_the_place_in_a_later_match_that_has_not_started(staff, club, hall):
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    final = fresh(game["final"])
    side = "a" if final.entry_a_id == semi.entry_a_id else "b"
    correct(staff, game, semi, semi.entry_b, games=LOST)
    final = fresh(final)
    assert getattr(final, f"entry_{side}_id") == semi.entry_b_id
    assert fresh(semi).winner_id == semi.entry_b_id
    assert not Resolution.objects.exists() and Event.objects.get(pk=game["event"]["id"]).paused_at is None


def test_a_changed_winner_never_silently_replaces_an_opponent_in_a_match_that_started(staff, club, hall):
    game = knockout(staff, club, hall)
    one, two = tables(hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    enter(staff, game, second, second.entry_a, games=GAMES)
    Hold.objects.filter(active=False).update(released_at=timezone.now() - timedelta(minutes=11))
    final = fresh(game["final"])
    send(staff, {**game, "match": final}, one)
    side = "a" if final.entry_a_id == first.entry_a_id else "b"

    shown = correct(staff, game, first, first.entry_b, games=LOST)
    assert shown["winner_id"] == str(first.entry_b_id)
    # The final is untouched and held; the event is paused; the organizers are asked.
    final = fresh(final)
    assert getattr(final, f"entry_{side}_id") == first.entry_a_id
    assert Event.objects.get(pk=game["event"]["id"]).paused_at is not None
    listed = staff.get(url(game["cup"]) + "corrections/").json()
    assert len(listed) == 1
    waiting = listed[0]
    assert (waiting["progress"], waiting["side"], waiting["resolved_at"]) == ("on_table", side, None)
    assert waiting["old_entry"] == official.title(first.entry_a)
    assert waiting["new_entry"] == official.title(first.entry_b)
    assert waiting["reason"] == "Sides were swapped on the sheet"
    detail = staff.get(url(game["cup"], event=game["event"]) + f"matches/{final.id}/").json()
    assert detail["held_for_correction"] is True
    with pytest.raises(ApiException) as refused, transaction.atomic():
        drawing.record_result(final, final.entry_a, games=GAMES)
    assert code_of(refused) == "held_for_correction"
    assert fresh(final).status == "scheduled"

    # Keep: the final stands with who is in it, and the event carries on.
    path = url(game["cup"]) + f"corrections/{waiting['id']}/resolve/"
    assert staff.post(path, {"choice": "keep"}, format="json").status_code == 400  # a note is required
    settled = staff.post(path, {"choice": "keep", "note": "Final already under way"}, format="json")
    assert settled.status_code == 200 and settled.json()[0]["choice"] == "keep"
    assert settled.json()[0]["resolved_by"] and settled.json()[0]["note"] == "Final already under way"
    assert getattr(fresh(final), f"entry_{side}_id") == first.entry_a_id
    assert Event.objects.get(pk=game["event"]["id"]).paused_at is None
    assert Reservation.objects.filter(match=final, status="active").exists()
    assert staff.post(path, {"choice": "keep", "note": "Again"}, format="json").json()["code"] == (
        "already_resolved"
    )


def test_replacing_strikes_out_what_was_played_and_keeps_it_on_record(staff, club, hall):
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    enter(staff, game, second, second.entry_a, games=GAMES)
    final = fresh(game["final"])
    side = "a" if final.entry_a_id == first.entry_a_id else "b"
    # The final has been scored and confirmed on a sheet, then decided.
    sheet = Scorecard.objects.create(match=final, revision=1)
    ScoreEvent.objects.create(
        id="00000000-0000-4000-8000-00000000e001", scorecard=sheet, sequence=1, payload={"type": "start"}
    )
    old_assignment = sheet.assignment_id
    enter(staff, game, final, first.entry_a, games=GAMES if side == "a" else LOST)

    correct(staff, game, first, first.entry_b, games=LOST)
    waiting = staff.get(url(game["cup"]) + "corrections/").json()[0]
    assert waiting["progress"] == "decided"
    path = url(game["cup"]) + f"corrections/{waiting['id']}/resolve/"
    settled = staff.post(path, {"choice": "replace", "note": "Final to be replayed"}, format="json")
    assert settled.status_code == 200, settled.json()

    final = fresh(final)
    assert (final.status, final.winner_id, final.games) == ("scheduled", None, [])
    assert getattr(final, f"entry_{side}_id") == first.entry_b_id
    # History is kept, not deleted: the struck-out result and the sheet's events.
    struck = OfficialResult.objects.get(match=final)
    assert (struck.current, struck.voided_at is not None) == (False, True)
    kept = Resolution.objects.get().struck_out
    assert kept["result"]["winner_id"] == str(first.entry_a_id)
    assert kept["sheets"][0]["events"][0]["event"] == {"type": "start"}
    assert kept["sheets"][0]["events"][0]["received_at"]
    assert sheet.assignments.filter(kind="reset", revision=1, assignment_id=old_assignment).exists()
    sheet.refresh_from_db()
    assert (sheet.revision, sheet.confirmed_at) == (0, None) and sheet.assignment_id != old_assignment
    assert not ScoreEvent.objects.exists()
    assert Event.objects.get(pk=game["event"]["id"]).paused_at is None
    detail = staff.get(url(game["cup"], event=game["event"]) + f"matches/{final.id}/").json()
    assert detail["result"] is None and detail["result_history"][0]["struck_out"] is True
    # And it can be played again.
    enter(staff, game, final, first.entry_b, games=GAMES if side == "a" else LOST)
    assert OfficialResult.objects.filter(match=final, current=True).count() == 1


def paused_final(staff, club, hall) -> tuple[dict, Match, str]:
    """A final on a table whose one side a correction put in question."""
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    enter(staff, game, second, second.entry_a, games=GAMES)
    Hold.objects.filter(active=False).update(released_at=timezone.now() - timedelta(minutes=11))
    final = fresh(game["final"])
    send(staff, {**game, "match": final}, tables(hall)[0])
    correct(staff, game, first, first.entry_b, games=LOST)
    return game, final, "a" if final.entry_a_id == first.entry_a_id else "b"


def test_a_paused_event_sends_nothing_out_and_cannot_be_completed(staff, club, hall):
    game, final, _side = paused_final(staff, club, hall)
    event = Event.objects.select_related("tournament").get(pk=game["event"]["id"])
    with pytest.raises(ApiException) as refused, transaction.atomic():
        lifecycle.complete_event(event.tournament, event, None)
    assert code_of(refused) == "event_paused"
    with transaction.atomic():
        reservations.recall(final, None, "Table needed")
    answer = send(staff, {**game, "match": final}, tables(hall)[0], expect=409)
    assert answer["code"] == "event_paused"


def test_correcting_back_withdraws_the_question_and_the_event_carries_on(staff, club, hall):
    game, final, side = paused_final(staff, club, hall)
    first = game["semis"][0]
    correct(staff, game, first, first.entry_a, games=GAMES, reason="The first sheet was right after all")
    listed = staff.get(url(game["cup"]) + "corrections/").json()
    assert [one["choice"] for one in listed] == ["withdrawn"]
    assert Event.objects.get(pk=game["event"]["id"]).paused_at is None
    assert getattr(fresh(final), f"entry_{side}_id") == first.entry_a_id
    # Nothing is left to decide: the withdrawn question can't put the loser into the final.
    path = url(game["cup"]) + f"corrections/{listed[0]['id']}/resolve/"
    settled = staff.post(path, {"choice": "replace", "note": "Too late"}, format="json")
    assert settled.status_code == 409 and settled.json()["code"] == "already_resolved"


def test_replacing_takes_the_match_off_its_table_and_the_replay_fills_the_place(staff, club, hall):
    game, final, side = paused_final(staff, club, hall)
    first = game["semis"][0]
    waiting = staff.get(url(game["cup"]) + "corrections/").json()[0]
    path = url(game["cup"]) + f"corrections/{waiting['id']}/resolve/"
    assert staff.post(path, {"choice": "replace", "note": "Not begun"}, format="json").status_code == 200
    final = fresh(final)
    assert (final.table_id, final.dispatched_at) == (None, None)
    assert getattr(final, f"entry_{side}_id") == first.entry_b_id
    assert not Reservation.objects.filter(match=final, status="active").exists()
    assert not Hold.objects.filter(active=True).exists()
    assert Event.objects.get(pk=game["event"]["id"]).paused_at is None


def test_only_competition_staff_enter_and_correct_results_and_players_see_no_history(staff, club, hall):
    from .helpers import logged_in, make_user

    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    visitor = logged_in(make_user("visitor@example.com", display_name="Visitor"))
    assert enter(visitor, game, semi, semi.entry_a, expect=403, games=GAMES)["code"] == "permission_denied"
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    assert correct(visitor, game, semi, semi.entry_b, expect=403, games=LOST)["code"] == "permission_denied"
    assert visitor.get(url(game["cup"]) + "corrections/").status_code == 403
    seen = visitor.get(url(game["cup"], event=game["event"]) + f"matches/{semi.id}/").json()
    assert seen["result"]["version"] == 1 and seen["result_history"] == []
    # Who recorded it, and why a correction was made, is the organizers' record.
    assert (seen["result"]["recorded_by"], seen["result"]["reason"]) == ("", "")
    assert seen["can_record_result"] is False
    assert fresh(semi).winner_id == semi.entry_a_id


def test_a_corrected_group_result_puts_the_right_qualifier_into_the_knockout(staff, club, hall):
    game = started(
        staff,
        club,
        hall,
        [["Amina"], ["Brian"], ["Chege"], ["Daudi"]],
        format="groups_knockout",
        group_count=2,
        qualifiers_per_group=1,
    )
    matches = Match.objects.filter(draw__event_id=game["event"]["id"])
    group = matches.filter(stage="group", group=1).get()
    final = matches.get(stage="knockout")
    enter(staff, game, group, group.entry_a, games=GAMES)
    final = fresh(final)
    side = "a" if final.entry_a_id == group.entry_a_id else "b"
    assert getattr(final, f"entry_{side}_id") == group.entry_a_id
    correct(staff, game, group, group.entry_b, games=LOST)
    assert getattr(fresh(final), f"entry_{side}_id") == group.entry_b_id
    assert not Resolution.objects.exists()


def groups(staff, club, hall, size: int, qualifiers: int) -> tuple[dict, Match, list[Match]]:
    """Two groups, both decided. Returns the match between the first group's first two (the first of
    them won it, and every other match of theirs) and the knockout's first round."""
    names = ["Amina", "Brian", "Chege", "Daudi", "Esther", "Faraji"][: size * 2]
    game = started(
        staff,
        club,
        hall,
        [[name] for name in names],
        format="groups_knockout",
        group_count=2,
        qualifiers_per_group=qualifiers,
    )
    matches = Match.objects.filter(draw__event_id=game["event"]["id"])
    first = list(matches.filter(stage="group", group=1).order_by("id"))
    order = sorted({entry for match in first for entry in (match.entry_a_id, match.entry_b_id)})
    for match in matches.filter(stage="group"):
        a_wins = match.group != 1 or order.index(match.entry_a_id) < order.index(match.entry_b_id)
        enter(staff, game, match, match.entry_a if a_wins else match.entry_b, games=GAMES if a_wins else LOST)
    top = next(match for match in first if {match.entry_a_id, match.entry_b_id} == set(order[:2]))
    first_round = matches.filter(stage="knockout", round=1).order_by("position")
    return game, fresh(top), [fresh(match) for match in first_round]


def flip(staff, game, match: Match, **body) -> None:
    """Correct `match` so that its other side won it."""
    a_won = match.winner_id == match.entry_a_id
    loser = match.entry_b if a_won else match.entry_a
    correct(staff, game, match, loser, games=LOST if a_won else GAMES, **body)


def test_a_match_kept_as_played_is_not_put_in_question_again_by_the_same_group(staff, club, hall):
    game, group, (final,) = groups(staff, club, hall, size=2, qualifiers=1)
    enter(staff, game, final, final.entry_a, games=GAMES)
    flip(staff, game, group)
    waiting = staff.get(url(game["cup"]) + "corrections/").json()[0]
    path = url(game["cup"]) + f"corrections/{waiting['id']}/resolve/"
    assert staff.post(path, {"choice": "keep", "note": "Final stands"}, format="json").status_code == 200
    # Only a game's points change: the same entry still leads the group, and the final was kept.
    group = fresh(group)
    a_won = group.winner_id == group.entry_a_id
    games = [[11, 5], [11, 7], [11, 8]] if a_won else [[5, 11], [7, 11], [8, 11]]
    correct(staff, game, group, group.winner, games=games, reason="8, not 9")
    assert Resolution.objects.count() == 1
    assert Event.objects.get(pk=game["event"]["id"]).paused_at is None


def test_qualifiers_that_swap_between_matches_are_decided_together(staff, club, hall):
    game, group, knockout_round = groups(staff, club, hall, size=3, qualifiers=2)
    pair = (group.entry_a_id, group.entry_b_id)
    holds = {
        (match.id, side): getattr(match, f"entry_{side}_id")
        for match in knockout_round
        for side in ("a", "b")
        if getattr(match, f"entry_{side}_id") in pair
    }
    assert len(holds) == 2 and len({match_id for match_id, _ in holds}) == 2
    played = next(match for match in knockout_round if (match.id, "a") in holds or (match.id, "b") in holds)
    enter(staff, game, played, played.entry_a, games=GAMES)
    flip(staff, game, group)
    # One of the two matches has been played, so neither place of the swap changes by itself.
    for (match_id, side), entry in holds.items():
        assert getattr(Match.objects.get(pk=match_id), f"entry_{side}_id") == entry
    listed = staff.get(url(game["cup"]) + "corrections/").json()
    assert sorted(one["progress"] for one in listed) == ["decided", "not_started"]
    for one in listed:
        path = url(game["cup"]) + f"corrections/{one['id']}/resolve/"
        assert staff.post(path, {"choice": "replace", "note": "Swap both"}, format="json").status_code == 200
    swapped = {pair[0]: pair[1], pair[1]: pair[0]}
    for (match_id, side), entry in holds.items():
        assert getattr(Match.objects.get(pk=match_id), f"entry_{side}_id") == swapped[entry]
    assert Event.objects.get(pk=game["event"]["id"]).paused_at is None


def test_a_rubber_is_corrected_only_while_the_tie_still_ends_the_same(staff, club):
    from .test_draws import draw_url
    from .test_ties import begin, decide, team
    from .test_tournaments import add_event, do, make_tournament

    cup = make_tournament(staff, club, make_venue(staff, club))
    cup = add_event(staff, cup, name="Teams", kind="team", format="round_robin")
    cup = do(staff, cup, "publish")
    event = cup["events"][0]
    tudor, tudor_players = team(staff, cup, event, "Tudor")
    nyali, nyali_players = team(staff, cup, event, "Nyali")
    staff.post(draw_url(cup, event, "preview"), {"rng_seed": 1}, format="json")
    staff.post(draw_url(cup, event, "publish"), {}, format="json")
    do(staff, cup, "start")
    do(staff, cup, "start", event=event)
    match = Match.objects.get(draw__event_id=event["id"])
    tie = {
        "cup": cup, "event": event, "match": match, "tudor": tudor, "tudor_players": tudor_players,
        "nyali": nyali, "nyali_players": nyali_players,
    }  # fmt: skip
    rubbers = begin(staff, tie)
    for rubber, winner in zip(rubbers, ("tudor", "nyali", "tudor", "tudor"), strict=False):
        decide(rubber, tie, winner)
    match = fresh(match)
    assert match.status == "completed" and OfficialResult.objects.filter(match=match).count() == 5
    tudor_entry = match.entry_a if str(match.entry_a_id) == tudor["id"] else match.entry_b
    nyali_entry = match.entry_b if tudor_entry.id == match.entry_a_id else match.entry_a
    a_is_tudor = tudor_entry.id == match.entry_a_id
    # The score of a rubber: the tie ends the same, so it is simply corrected and its history kept.
    closer = [[11, 9], [11, 9], [12, 10]] if a_is_tudor else [[9, 11], [9, 11], [10, 12]]
    shown = correct(staff, tie, match, tudor_entry, rubber_id=str(rubbers[0].id), games=closer)
    assert shown["tie"]["rubbers"][0]["games"] == closer
    assert [v["rubber"] for v in shown["result_history"] if v["version"] == 2] == [1]
    # Giving Nyali the first rubber would have ended the tie differently: refused, nothing changes.
    other = [[9, 11], [9, 11], [10, 12]] if a_is_tudor else [[11, 9], [11, 9], [12, 10]]
    refused = correct(staff, tie, match, nyali_entry, expect=409, rubber_id=str(rubbers[0].id), games=other)
    assert refused["code"] == "tie_would_change"
    # And the tie itself is corrected through its rubbers.
    assert (
        correct(staff, tie, match, nyali_entry, expect=409, outcome="walkover")["code"]
        == "correct_the_rubbers"
    )
    assert fresh(match).winner_id == tudor_entry.id
    assert OfficialResult.objects.filter(match=match, current=True).count() == 5
