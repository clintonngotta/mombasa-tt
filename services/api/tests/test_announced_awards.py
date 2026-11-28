"""The organizers' own awards (best player, best umpire, fair play, anything they name) in the results
announcement, and a best umpire given to the umpire's account (user request, 2026-11-28)."""

import pytest

from reservations.models import TournamentUmpire

from .helpers import make_user
from .test_announcements import generate, knockout  # noqa: F401
from .test_reservations import person

pytestmark = pytest.mark.django_db


def awards_url(game) -> str:
    return f"/api/v1/tournaments/{game['cup']['id']}/ceremony/awards/"


def award(staff, game, expect=201, **body) -> dict:
    response = staff.post(awards_url(game), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_a_tournament_announcement_lists_the_organizers_awards(staff, knockout):  # noqa: F811
    player = person("Amina Hassan")
    knockout["semis"][0].entry_a.players.update(user=player)
    award(staff, knockout, title="Best player", recipient_id=str(player.id), prize="Trophy")
    award(staff, knockout, title="Spirit of the game", recipient_name="Coach Juma")
    award(staff, knockout, title="Fair play")

    body = generate(staff, knockout, scope="tournament")["body"]

    awards = body.split("\nAwards\n", 1)[1].splitlines()
    assert awards == [
        "Best player: Amina Hassan (Trophy)",
        "Spirit of the game: Coach Juma",
        "Fair play: to be announced",
    ]
    # An event's announcement lists only awards given in that event; these are the tournament's.
    assert "Awards" not in generate(staff, knockout, scope="event", event_id=knockout["event"]["id"])["body"]


def test_best_umpire_goes_to_a_tournament_umpire_and_not_to_a_stranger(staff, knockout):  # noqa: F811
    umpire = make_user("zuri.umpire@example.com", display_name="Zuri Umpire")
    stranger = make_user("stranger@example.com")
    refused = award(staff, knockout, expect=400, title="Best umpire", recipient_id=str(umpire.id))
    assert "recipient_id" in refused["fields"]
    TournamentUmpire.objects.create(tournament_id=knockout["cup"]["id"], user=umpire)
    given = award(staff, knockout, title="Best umpire", recipient_id=str(umpire.id))
    assert given["awards"][-1]["receives"] == "Zuri Umpire"
    award(staff, knockout, expect=400, title="Best fan", recipient_id=str(stranger.id))
    assert "Best umpire: Zuri Umpire" in generate(staff, knockout, scope="tournament")["body"]
