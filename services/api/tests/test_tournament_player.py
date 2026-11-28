"""One player in one tournament (TASK-148): profile as the reader may see it, and their record there."""

import pytest
from django.utils import timezone

from competitions.models import Entry, EntryPlayer, Match
from profiles.models import PlayerProfile

from .helpers import logged_in
from .test_draws import draw_url, fill
from .test_entries import enter, player
from .test_guests import new_guest
from .test_standings import decide
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db


def player_url(tournament, user_id) -> str:
    return url(tournament) + f"players/{user_id}/"


@pytest.fixture
def cup(staff, club):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(staff, tournament, name="League", format="round_robin")
    add_event(staff, tournament, name="Doubles", kind="doubles")
    return do(staff, tournament, "publish")


def publish_draw(staff, cup, event) -> None:
    staff.post(draw_url(cup, event, "preview"), {"rng_seed": 5}, format="json")
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200


def test_a_players_record_lists_their_matches_results_and_totals(staff, cup):
    league = cup["events"][0]
    entries = fill(staff, cup, league, 3)
    publish_draw(staff, cup, league)
    me = entries[0]["players"][0]["id"]
    matches = [
        m for m in Match.objects.filter(draw__event_id=league["id"]).select_related("entry_a", "entry_b")
    ]
    mine = [
        m for m in matches if str(m.entry_a_id) == entries[0]["id"] or str(m.entry_b_id) == entries[0]["id"]
    ]
    assert len(mine) == 2
    decide(mine[0], a_wins=str(mine[0].entry_a_id) == entries[0]["id"])  # won
    decide(mine[1], a_wins=str(mine[1].entry_a_id) != entries[0]["id"])  # lost

    response = logged_in(player("Viewer")).get(player_url(cup, me))
    assert response.status_code == 200, response.json()
    body = response.json()
    assert (body["won"], body["lost"]) == (1, 1)
    assert body["player"]["display_name"] == "League0"
    [event] = body["events"]
    assert event["event"]["name"] == "League"
    assert event["entry_status"] == "accepted"
    assert event["group_rank"] in {1, 2, 3}
    assert sorted(m["result"] for m in event["matches"]) == ["lost", "won"]
    for shown in event["matches"]:
        assert shown[shown["side"]]["entry"]["id"] == entries[0]["id"]

    # Signed out, the published tournament reads the same; the profile is the name alone.
    from rest_framework.test import APIClient

    visitor = APIClient().get(player_url(cup, me))
    assert visitor.status_code == 200
    assert visitor.json()["won"] == 1
    assert visitor.json()["has_player_page"] is False


def test_a_player_not_in_the_tournament_or_an_unknown_id_is_not_found(staff, cup):
    fill(staff, cup, cup["events"][0], 2)
    viewer = logged_in(player("Viewer"))
    assert viewer.get(player_url(cup, player("Outsider").id)).status_code == 404
    assert viewer.get(player_url(cup, "00000000-0000-0000-0000-000000000000")).status_code == 404


def test_a_draft_tournament_is_not_found_for_anybody_but_its_staff(staff, club):
    draft = make_tournament(staff, club, make_venue(staff, club))
    event = add_event(staff, draft)["events"][0]
    # A draft takes no entries through the desk; one made before (say, imported) is enough here.
    early = player("Early")
    entry = Entry.objects.create(event_id=event["id"], status=Entry.Status.ACCEPTED)
    EntryPlayer.objects.create(entry=entry, event_id=event["id"], user=early)
    me = early.id
    assert logged_in(player("Viewer")).get(player_url(draft, me)).status_code == 404
    assert staff.get(player_url(draft, me)).status_code == 200


def test_entries_others_may_not_see_stay_hidden(staff, club):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(staff, tournament, admission="closed")
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    hopeful = player("Hopeful")
    hopeful.email_verified_at = timezone.now()
    hopeful.save(update_fields=["email_verified_at"])
    own = logged_in(hopeful)
    enter(own, tournament, event)  # closed admission: pending until staff decide
    assert logged_in(player("Viewer")).get(player_url(tournament, hopeful.id)).status_code == 404
    assert own.get(player_url(tournament, hopeful.id)).json()["events"][0]["entry_status"] == "pending"
    assert staff.get(player_url(tournament, hopeful.id)).status_code == 200


def test_only_a_listed_players_published_details_show(staff, cup):
    league = cup["events"][0]
    entries = fill(staff, cup, league, 2)
    me = entries[0]["players"][0]["id"]
    PlayerProfile.objects.update_or_create(
        user_id=me,
        defaults={"hand": "left", "bio": "Loop", "style": "Attacker", "published_details": ["hand"]},
    )
    viewer = logged_in(player("Viewer"))
    unlisted = viewer.get(player_url(cup, me)).json()
    assert unlisted["has_player_page"] is False
    assert unlisted["player"]["hand"] is None and unlisted["player"]["clubs"] == []

    PlayerProfile.objects.filter(user_id=me).update(directory_opt_in=True)
    listed = viewer.get(player_url(cup, me)).json()
    assert listed["has_player_page"] is True
    assert listed["player"]["hand"] == "left"
    assert listed["player"]["bio"] is None and listed["player"]["style"] is None  # never published
    assert "email" not in listed["player"] and "city" not in listed["player"]


def test_a_guest_shows_by_name_with_their_record(staff, club, cup):
    league = cup["events"][0]
    guest = new_guest(staff, club, "Juma")
    enter(staff, cup, league, player_ids=[guest["id"]])
    fill(staff, cup, league, 1)
    body = logged_in(player("Viewer")).get(player_url(cup, guest["id"])).json()
    assert body["player"]["display_name"] == "Juma"
    assert body["has_player_page"] is False
    assert body["events"][0]["entry_status"] == "accepted"


def test_a_jumbles_player_sees_every_round_with_a_new_partner_and_their_pool_rank(staff, club):
    from .test_jumbles import jumbles_event, person, played

    tournament, event = jumbles_event(staff, club)
    star = person("Amani")
    for match in played(staff, tournament, event):
        a_has_star = star.id in {p.user_id for p in match.entry_a.players.all()}
        decide(match, a_wins=a_has_star or star.id not in {p.user_id for p in match.entry_b.players.all()})

    body = logged_in(player("Viewer")).get(player_url(tournament, star.id)).json()
    [shown] = body["events"]
    assert shown["entry"]["players"][0]["display_name"] == "Amani"
    rounds = Match.objects.filter(draw__event_id=event["id"]).values("round").distinct().count()
    assert len(shown["matches"]) == rounds and all(m["result"] == "won" for m in shown["matches"])
    partners = {
        next(p["display_name"] for p in m[m["side"]]["entry"]["players"] if p["id"] != str(star.id))
        for m in shown["matches"]
    }
    assert len(partners) == rounds
    assert shown["group_rank"] == 1 and shown["placement"] == "Winner"
