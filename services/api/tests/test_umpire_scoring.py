"""Umpire assignment, scoring and confirmation (REQ-012, EVAL-012, TASK-024): only the assigned umpire
scores, the server replays every event itself, and only a finished match can be confirmed."""

import uuid

import pytest

from competitions.models import Match, OfficialResult, Rubber
from organizations.models import Role
from scoring.models import Scorecard, ScoreEvent

from .helpers import logged_in, make_user
from .test_draws import draw_url, fill
from .test_roles import add_member
from .test_ties import begin, team
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
START = {"type": "start", "server": "a1", "a_end": "left"}


def point(side: str) -> dict:
    return {"type": "point", "side": side}


@pytest.fixture
def umpire(club):
    user = make_user("umpire@example.com", display_name="Zuri Umpire")
    add_member(club, user, scorers(club))
    return user


def scorers(club) -> Role:
    """A role that lets its holders score matches they are assigned and nothing else."""
    return Role.objects.get_or_create(
        organization=club, name="Scorers", defaults={"permissions": ["scoring.assigned"]}
    )[0]


@pytest.fixture
def final(staff, club):
    """A two-player knockout that has started: one match, the final, best of 3."""
    tournament = make_tournament(staff, club, make_venue(staff, club))
    tournament = add_event(staff, tournament, name="Singles", format="knockout", best_of=3)
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    fill(staff, tournament, event, 2)
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    match = Match.objects.get(draw__event_id=event["id"])
    return {"cup": tournament, "event": event, "match": match}


def match_url(game, action="") -> str:
    return url(game["cup"], event=game["event"]) + f"matches/{game['match'].id}/" + action


def assign(staff, game, user, expect=200, **extra) -> dict:
    body = {"user_id": str(user.id) if user else None, **extra}
    response = staff.post(match_url(game, "umpire/"), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


class Deck:
    """What the scoring deck does: keeps the assignment and the next sequence number."""

    def __init__(self, client, scorecard_id):
        self.client = client
        self.path = f"/api/v1/scorecards/{scorecard_id}/"
        sheet = client.get(self.path)
        assert sheet.status_code == 200, sheet.json()
        self.assignment_id = sheet.json()["assignment_id"]
        self.sequence = sheet.json()["revision"]

    def envelope(self, event: dict) -> dict:
        self.sequence += 1
        return {"id": str(uuid.uuid4()), "sequence": self.sequence, "event": event}

    def send(self, *events: dict, expect=200) -> dict:
        body = {"assignment_id": self.assignment_id, "events": [self.envelope(e) for e in events]}
        response = self.client.post(self.path + "events/", body, format="json")
        assert response.status_code == expect, response.json()
        return response.json()

    def confirm(self, revision=None, expect=200) -> dict:
        body = {
            "assignment_id": self.assignment_id,
            "revision": self.sequence if revision is None else revision,
        }
        response = self.client.post(self.path + "confirm/", body, format="json")
        assert response.status_code == expect, response.json()
        return response.json()


def test_staff_assign_an_umpire_and_only_that_umpire_gets_the_sheet(staff, club, final, umpire):
    as_umpire = logged_in(umpire)
    stranger = make_user("stranger@example.com")
    able = staff.get(url(final["cup"], event=final["event"]) + "umpires/").json()
    assert sorted(person["display_name"] for person in able) == ["Club Admin", "Zuri Umpire"]

    # Somebody the club hasn't trusted with scoring, and one of the two players, can't be assigned.
    assert assign(staff, final, stranger, expect=409)["code"] == "not_an_umpire"
    player = final["match"].entry_a.players.get().user
    add_member(club, player, scorers(club))
    assert assign(staff, final, player, expect=409)["code"] == "umpire_plays"
    # Only competition staff assign.
    refused = as_umpire.post(match_url(final, "umpire/"), {"user_id": str(umpire.id)}, format="json")
    assert refused.status_code == 403

    shown = assign(staff, final, umpire)["scoring"]
    assert shown == {
        "scorecard_id": None,  # the sheet's id goes to its umpire only
        "status": "assigned",
        "umpire_name": "Zuri Umpire",
        "can_score": False,
        "can_assign": True,
        "incidents": [],
        "live": None,
    }
    mine = as_umpire.get(match_url(final)).json()["scoring"]
    assert mine["can_score"] is True and mine["can_assign"] is False
    seen = logged_in(stranger).get(match_url(final)).json()["scoring"]
    assert (seen["scorecard_id"], seen["can_score"], seen["umpire_name"]) == (None, False, "Zuri Umpire")

    listed = as_umpire.get("/api/v1/me/scorecards/").json()["results"]
    assert [sheet["id"] for sheet in listed] == [mine["scorecard_id"]]
    assert (listed[0]["label"], listed[0]["status"], listed[0]["event_name"]) == (
        "Final",
        "assigned",
        "Singles",
    )
    assert "events" not in listed[0]
    assert staff.get("/api/v1/me/scorecards/").json()["results"] == []

    sheet = as_umpire.get(f"/api/v1/scorecards/{mine['scorecard_id']}/").json()
    assert sheet["config"] == {"best_of": 3, "doubles": False}
    assert sheet["incidents"] == [] and sheet["can_disqualify"] is False
    assert sheet["state"]["status"] == "not_started" and sheet["revision"] == 0 and sheet["events"] == []
    assert [p["slot"] for p in sheet["a"]["players"]] == ["a1"]
    assert sheet["a"]["title"] == final["match"].entry_a.players.get().user.display_name
    # For everybody else, staff included, the sheet doesn't exist.
    for client in (staff, logged_in(stranger), logged_in(player)):
        assert client.get(f"/api/v1/scorecards/{mine['scorecard_id']}/").status_code == 404
        sent = client.post(
            f"/api/v1/scorecards/{mine['scorecard_id']}/events/",
            {
                "assignment_id": sheet["assignment_id"],
                "events": [{"id": str(uuid.uuid4()), "sequence": 1, "event": START}],
            },
            format="json",
        )
        assert sent.status_code == 404
        assert (
            client.post(
                f"/api/v1/scorecards/{mine['scorecard_id']}/confirm/",
                {"assignment_id": sheet["assignment_id"], "revision": 0},
                format="json",
            ).status_code
            == 404
        )
    assert not ScoreEvent.objects.exists()


def test_the_umpire_scores_a_match_and_confirming_makes_it_official(staff, final, umpire):
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    deck = Deck(as_umpire, as_umpire.get(match_url(final)).json()["scoring"]["scorecard_id"])

    viewer = logged_in(make_user("bracket-viewer@example.com"))
    bracket_url = draw_url(final["cup"], final["event"])
    assert viewer.get(bracket_url).json()["published"]["matches"][0]["is_live"] is False

    started = deck.send(START, point("a"), point("a"))
    assert (started["accepted"], started["refused"], started["revision"], started["status"]) == (
        3,
        None,
        3,
        "in_progress",
    )
    assert started["state"]["points"] == [2, 0] and started["state"]["server"] == "b1"
    assert as_umpire.get(match_url(final)).json()["scoring"]["status"] == "in_progress"
    assert viewer.get(bracket_url).json()["published"]["matches"][0]["is_live"] is True

    # An early finish is not a result.
    assert deck.confirm(expect=409)["code"] == "match_not_finished"
    assert Match.objects.get(pk=final["match"].pk).status == "scheduled"

    deck.send(*[point("a")] * 9)  # 11-0
    deck.send(*[point("b")] * 11)  # 0-11
    finished = deck.send(*[point("a")] * 11)
    assert (finished["status"], finished["state"]["winner"], finished["revision"]) == ("finished", "a", 34)
    assert viewer.get(bracket_url).json()["published"]["matches"][0]["is_live"] is False
    # The match is over: nothing more is scored, and the stream stays where it was.
    over = deck.send(point("b"))
    assert (over["accepted"], over["refused"]) == (0, {"sequence": 35, "code": "not_in_progress"})
    deck.sequence = 34

    # Still not official, and a confirmation that hasn't seen every event is refused.
    assert Match.objects.get(pk=final["match"].pk).status == "scheduled"
    assert deck.confirm(revision=33, expect=409)["code"] == "stale_revision"
    confirmed = deck.confirm()
    assert confirmed["status"] == "confirmed" and confirmed["confirmed_at"]
    match = Match.objects.get(pk=final["match"].pk)
    assert (match.status, match.winner_id, match.outcome) == ("completed", match.entry_a_id, "played")
    assert match.games == [[11, 0], [0, 11], [11, 0]]
    shown = as_umpire.get(match_url(final)).json()
    assert shown["scoring"] == {
        "scorecard_id": shown["scoring"]["scorecard_id"],
        "status": "confirmed",
        "umpire_name": "Zuri Umpire",
        "can_score": False,
        "can_assign": False,
        "incidents": [],
        "live": None,
    }
    # A confirmed result is closed to the deck: corrections are the organizers' (REQ-015).
    # Confirming again (the first answer was lost on the way) changes nothing and succeeds.
    assert deck.confirm()["status"] == "confirmed"
    assert OfficialResult.objects.filter(match=match).count() == 1
    assert deck.send(point("b"), expect=409)["code"] == "already_confirmed"
    assert as_umpire.get("/api/v1/me/scorecards/").json()["results"] == []


def test_events_are_replayed_in_order_and_retries_are_harmless(staff, final, umpire):
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    deck = Deck(as_umpire, as_umpire.get(match_url(final)).json()["scoring"]["scorecard_id"])
    first = [deck.envelope(START), deck.envelope(point("a"))]
    body = {"assignment_id": deck.assignment_id, "events": first}
    assert as_umpire.post(deck.path + "events/", body, format="json").json()["accepted"] == 2
    # The same request again (a retry after a lost reply) changes nothing.
    again = as_umpire.post(deck.path + "events/", body, format="json").json()
    assert (again["accepted"], again["refused"], again["revision"]) == (0, None, 2)
    # A retry that carries one new event accepts just that one.
    third = deck.envelope(point("b"))
    more = as_umpire.post(
        deck.path + "events/", {"assignment_id": deck.assignment_id, "events": [*first, third]}, format="json"
    ).json()
    assert (more["accepted"], more["revision"], more["state"]["points"]) == (1, 3, [1, 1])

    def refused(event_id, sequence, event=None) -> dict:
        sent = {"id": str(event_id), "sequence": sequence, "event": event or point("a")}
        reply = as_umpire.post(
            deck.path + "events/", {"assignment_id": deck.assignment_id, "events": [sent]}, format="json"
        )
        assert reply.status_code == 200, reply.json()
        assert reply.json()["accepted"] == 0
        return reply.json()["refused"]

    assert refused(uuid.uuid4(), 5) == {"sequence": 5, "code": "sequence_gap"}
    # A device that says it has seen a later revision than the server holds built on something else.
    ahead = {"id": str(uuid.uuid4()), "sequence": 4, "event": point("a"), "expected_revision": 9}
    reply = as_umpire.post(
        deck.path + "events/", {"assignment_id": deck.assignment_id, "events": [ahead]}, format="json"
    ).json()
    assert (reply["accepted"], reply["refused"]) == (0, {"sequence": 4, "code": "revision_conflict"})
    # Having seen less than the server holds is normal after a lost reply: the retry is still taken.
    behind = [{**sent, "expected_revision": 0} for sent in [*first, third]]
    reply = as_umpire.post(
        deck.path + "events/", {"assignment_id": deck.assignment_id, "events": behind}, format="json"
    ).json()
    assert (reply["accepted"], reply["refused"], reply["revision"]) == (0, None, 3)
    assert refused(uuid.uuid4(), 2) == {"sequence": 2, "code": "sequence_conflict"}  # another event's place
    assert refused(first[0]["id"], 4) == {"sequence": 4, "code": "sequence_conflict"}  # an id used before
    assert refused(uuid.uuid4(), 4, {"type": "start", "server": "a1", "a_end": "left"}) == {
        "sequence": 4,
        "code": "already_started",
    }
    assert refused(uuid.uuid4(), 4, {"type": "bogus"}) == {"sequence": 4, "code": "unknown_event"}
    # A batch stops at the first event that is refused and keeps what came before it.
    mixed = [
        {"id": str(uuid.uuid4()), "sequence": 4, "event": point("a")},
        {"id": str(uuid.uuid4()), "sequence": 5, "event": {"type": "timeout", "side": "a"}},
        {"id": str(uuid.uuid4()), "sequence": 6, "event": {"type": "timeout", "side": "a"}},
        {"id": str(uuid.uuid4()), "sequence": 7, "event": point("a")},
    ]
    reply = as_umpire.post(
        deck.path + "events/", {"assignment_id": deck.assignment_id, "events": mixed}, format="json"
    ).json()
    assert (reply["accepted"], reply["refused"], reply["revision"]) == (
        2,
        {"sequence": 6, "code": "timeout_used"},
        5,
    )
    assert reply["state"]["points"] == [2, 1] and reply["state"]["timeouts"] == [True, False]
    # Undo is an event like any other and stays in the stream.
    deck.sequence = 5
    undone = deck.send({"type": "undo"})
    assert undone["state"]["timeouts"] == [False, False] and undone["revision"] == 6
    sheet = as_umpire.get(deck.path).json()
    assert [e["sequence"] for e in sheet["events"]] == [1, 2, 3, 4, 5, 6]
    assert sheet["events"][-1]["event"] == {"type": "undo"} and sheet["state"] == undone["state"]


def test_reassigning_cuts_off_the_old_device_and_keeps_the_score(staff, final, umpire, admin):
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    deck = Deck(as_umpire, as_umpire.get(match_url(final)).json()["scoring"]["scorecard_id"])
    deck.send(START, point("a"))

    # The same umpire assigned again (a new device): the old assignment id no longer works.
    assign(staff, final, umpire)
    assert deck.send(point("a"), expect=409)["code"] == "stale_assignment"
    assert deck.confirm(revision=2, expect=409)["code"] == "stale_assignment"
    fresh = Deck(as_umpire, deck.path.split("/")[-2])
    assert fresh.sequence == 2 and fresh.assignment_id != deck.assignment_id
    assert fresh.send(point("a"))["state"]["points"] == [2, 0]

    # Somebody else assigned: the first umpire loses the sheet altogether.
    assign(staff, final, admin)
    assert as_umpire.get(fresh.path).status_code == 404
    assert (
        as_umpire.post(
            fresh.path + "events/",
            {"assignment_id": fresh.assignment_id, "events": [fresh.envelope(point("a"))]},
            format="json",
        ).status_code
        == 404
    )
    taken_over = Deck(staff, fresh.path.split("/")[-2])
    assert taken_over.sequence == 3
    assert taken_over.send(point("b"))["state"]["points"] == [2, 1]
    # Taken back from everybody: nobody can score, and the match page says so.
    assert assign(staff, final, None)["scoring"]["umpire_name"] == ""
    assert staff.get(taken_over.path).status_code == 404
    assert Scorecard.objects.get().revision == 4


def test_a_match_is_scored_only_while_its_event_is_in_progress(staff, club, umpire):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    tournament = add_event(staff, tournament, name="Singles", format="knockout")
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    fill(staff, tournament, event, 2)
    staff.post(draw_url(tournament, event, "preview"), {}, format="json")
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    game = {"cup": tournament, "event": event, "match": Match.objects.get(draw__event_id=event["id"])}
    assign(staff, game, umpire)  # assigned ahead of the day
    as_umpire = logged_in(umpire)
    deck = Deck(as_umpire, as_umpire.get(match_url(game)).json()["scoring"]["scorecard_id"])
    assert deck.send(START, expect=409)["code"] == "not_in_play"
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    deck.sequence = 0
    assert deck.send(START)["status"] == "in_progress"
    # A tie can't be given an umpire as a whole, and a singles match has no rubbers.
    assert assign(staff, game, umpire, expect=404, rubber_id=str(uuid.uuid4())) is not None


def test_a_tie_is_scored_rubber_by_rubber(staff, club, umpire):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    tournament = add_event(
        staff,
        tournament,
        name="Teams",
        kind="team",
        format="round_robin",
        best_of=3,
        tie_rubbers=["singles", "doubles", "singles"],
    )
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    tudor, tudor_players = team(staff, tournament, event, "Tudor")
    nyali, nyali_players = team(staff, tournament, event, "Nyali")
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    match = Match.objects.get(draw__event_id=event["id"])
    tie = {"cup": tournament, "event": event, "match": match, "tudor": tudor, "nyali": nyali}
    tie |= {"tudor_players": tudor_players, "nyali_players": nyali_players}
    order = ((0,), (0, 1), (2,))
    from .test_ties import hand_in, picks

    hand_in(staff, tie, "tudor", picks(tudor_players, order))
    hand_in(staff, tie, "nyali", picks(nyali_players, order))
    rubbers = list(Rubber.objects.filter(match=match))
    assert begin is not None and len(rubbers) == 3

    assert assign(staff, tie, umpire, expect=409)["code"] == "score_rubbers"
    for rubber in rubbers:
        shown = assign(staff, tie, umpire, rubber_id=str(rubber.id))
    as_umpire = logged_in(umpire)
    by_position = {
        r["position"]: r["scoring"] for r in as_umpire.get(match_url(tie)).json()["tie"]["rubbers"]
    }
    assert shown["scoring"] is None and all(s["can_score"] for s in by_position.values())

    second = Deck(as_umpire, by_position[2]["scorecard_id"])
    assert second.send(START | {"receiver": "b1"}, expect=409)["code"] == "rubber_out_of_turn"
    first = Deck(as_umpire, by_position[1]["scorecard_id"])
    sheet = as_umpire.get(first.path).json()
    assert sheet["label"] == "Round 1 · Rubber 1" and sheet["config"] == {"best_of": 3, "doubles": False}
    assert sheet["a"]["title"].endswith(f"({match.entry_a.team_name})")
    first.send(START)
    assert as_umpire.get(match_url(tie)).json()["is_live"] is True
    first.send(*[point("a")] * 22)
    assert as_umpire.get(match_url(tie)).json()["is_live"] is False
    first.confirm()
    assert Rubber.objects.get(pk=rubbers[0].pk).status == "completed"

    second = Deck(as_umpire, by_position[2]["scorecard_id"])
    doubles = as_umpire.get(second.path).json()
    assert doubles["config"]["doubles"] is True and [p["slot"] for p in doubles["b"]["players"]] == [
        "b1",
        "b2",
    ]
    second.send(START | {"receiver": "b2"}, *[point("a")] * 22)
    second.confirm()
    # Two wins of three: the tie is decided and the third rubber is not played or scored.
    match.refresh_from_db()
    assert (match.status, match.winner_id) == ("completed", match.entry_a_id)
    third = as_umpire.get(match_url(tie)).json()["tie"]["rubbers"][2]
    assert (third["status"], third["scoring"]["can_score"]) == ("not_played", False)
    last = Deck(as_umpire, by_position[3]["scorecard_id"])
    assert last.send(START, expect=409)["code"] == "match_decided"


def test_an_umpire_who_loses_the_role_loses_the_sheet(staff, club, final, umpire):
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    deck = Deck(as_umpire, as_umpire.get(match_url(final)).json()["scoring"]["scorecard_id"])
    deck.send(START, *[point("a")] * 22)
    membership = club.memberships.get(user=umpire)
    membership.roles.clear()  # still a member, no longer trusted with scoring

    assert as_umpire.get(deck.path).status_code == 404
    assert as_umpire.get("/api/v1/me/scorecards/").json()["results"] == []
    body = {"assignment_id": deck.assignment_id, "events": [deck.envelope({"type": "undo"})]}
    assert as_umpire.post(deck.path + "events/", body, format="json").status_code == 404
    assert deck.confirm(revision=23, expect=404) is not None
    shown = as_umpire.get(match_url(final)).json()["scoring"]
    assert (shown["scorecard_id"], shown["can_score"]) == (None, False)
    assert Match.objects.get(pk=final["match"].pk).status == "scheduled"
    # Given the role back, the sheet and everything scored are there again.
    membership.roles.add(scorers(club))
    assert as_umpire.get(deck.path).json()["revision"] == 23


def test_lineups_cannot_be_cleared_under_a_rubber_being_scored(staff, club, umpire):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    tournament = add_event(
        staff, tournament, name="Teams", kind="team", format="round_robin", tie_rubbers=["singles"]
    )
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    tudor, tudor_players = team(staff, tournament, event, "Tudor")
    nyali, nyali_players = team(staff, tournament, event, "Nyali")
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    match = Match.objects.get(draw__event_id=event["id"])
    tie = {"cup": tournament, "event": event, "match": match, "tudor": tudor, "nyali": nyali}
    from .test_ties import hand_in, picks

    hand_in(staff, tie, "tudor", picks(tudor_players, ((0,),)))
    hand_in(staff, tie, "nyali", picks(nyali_players, ((0,),)))
    rubber = Rubber.objects.get(match=match)
    assign(staff, tie, umpire, rubber_id=str(rubber.id))
    as_umpire = logged_in(umpire)
    sheet = as_umpire.get(match_url(tie)).json()["tie"]["rubbers"][0]["scoring"]["scorecard_id"]
    Deck(as_umpire, sheet).send(START, point("a"))
    refused = staff.post(match_url(tie, "lineup/reset/"), {}, format="json")
    assert (refused.status_code, refused.json()["code"]) == (409, "tie_under_way")
    assert ScoreEvent.objects.count() == 2


def test_a_sheet_of_a_superseded_draw_is_no_longer_listed(staff, club, umpire):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    tournament = add_event(staff, tournament, name="Singles", format="knockout")
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    fill(staff, tournament, event, 2)
    staff.post(draw_url(tournament, event, "preview"), {}, format="json")
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    game = {"cup": tournament, "event": event, "match": Match.objects.get(draw__event_id=event["id"])}
    assign(staff, game, umpire)
    as_umpire = logged_in(umpire)
    assert len(as_umpire.get("/api/v1/me/scorecards/").json()["results"]) == 1
    staff.post(draw_url(tournament, event, "preview"), {}, format="json")
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200
    assert as_umpire.get("/api/v1/me/scorecards/").json()["results"] == []
