"""Award ceremonies (REQ-049, EVAL-049): placement awards from results, the organizers' own awards,
order, publication, presenting and honours."""

import pytest

from competitions.models import Entry, Match

from .helpers import logged_in, make_user
from .test_official_results import enter, fresh, hall, knockout  # noqa: F401 (hall is a fixture)
from .test_reservations import started
from .test_tournaments import do

pytestmark = pytest.mark.django_db


def ceremony_url(game, path=""):
    return f"/api/v1/tournaments/{game['cup']['id']}/ceremony/{path}"


def play_knockout(staff, game):
    for semi in game["semis"]:
        semi = fresh(semi)
        enter(staff, game, semi, semi.entry_a, outcome="walkover")
    final = fresh(game["final"])
    enter(staff, game, final, final.entry_a, outcome="walkover")
    do(staff, game["cup"], "complete", event=game["event"])
    return fresh(final)


def names(entry_id) -> str:
    return " / ".join(p.user.display_name for p in Entry.objects.get(pk=entry_id).players.all())


def test_placement_awards_come_from_the_results_third_place_first(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    assert staff.post(ceremony_url(game, "generate/"), format="json").json()["awards"] == []  # not completed
    final = play_knockout(staff, game)
    made = staff.post(ceremony_url(game, "generate/"), format="json")
    assert made.status_code == 200, made.json()
    awards = made.json()["awards"]
    assert [(a["title"], a["place"], a["kind"]) for a in awards] == [
        ("Singles: Third place", 3, "placement"),
        ("Singles: Third place", 3, "placement"),
        ("Singles: Runner-up", 2, "placement"),
        ("Singles: Winner", 1, "placement"),
    ]
    assert awards[-1]["receives"] == names(final.winner_id)
    assert awards[2]["receives"] == names(final.entry_b_id)
    # Generating again gives the same awards, not twice as many.
    assert len(staff.post(ceremony_url(game, "generate/"), format="json").json()["awards"]) == 4


def test_a_round_robin_awards_its_top_three(staff, club, hall):  # noqa: F811
    game = started(staff, club, hall, [["Amina"], ["Brian"], ["Chege"]], format="round_robin")
    strength = {"Amina": 0, "Brian": 1, "Chege": 2}  # Amina beats everyone, Brian beats Chege
    for match in Match.objects.filter(draw__event_id=game["event"]["id"]).exclude(status=Match.Status.BYE):
        match = fresh(match)
        a, b = (strength[names(entry.id)] for entry in (match.entry_a, match.entry_b))
        enter(staff, game, match, match.entry_a if a < b else match.entry_b, outcome="walkover")
    do(staff, game["cup"], "complete", event=game["event"])
    awards = staff.post(ceremony_url(game, "generate/"), format="json").json()["awards"]
    assert [(a["place"], a["receives"]) for a in awards] == [(3, "Chege"), (2, "Brian"), (1, "Amina")]


def test_organizers_add_order_publish_and_present_awards(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    final = play_knockout(staff, game)
    staff.put(ceremony_url(game), {"location": "Main hall", "host": "Coach Juma"}, format="json")
    staff.post(ceremony_url(game, "generate/"), format="json")
    winner_user = Entry.objects.get(pk=final.winner_id).players.get().user
    special = staff.post(
        ceremony_url(game, "awards/"),
        {
            "title": "Fair play",
            "recipient_id": str(winner_user.id),
            "prize": "Trophy",
            "presenter": "Regional chair",
        },
        format="json",
    )
    assert special.status_code == 201, special.json()
    stranger = make_user("stranger@example.com")
    refused = staff.post(
        ceremony_url(game, "awards/"), {"title": "Best fan", "recipient_id": str(stranger.id)}, format="json"
    )
    assert refused.status_code == 400
    named = staff.post(
        ceremony_url(game, "awards/"),
        {"title": "Best umpire", "recipient_name": "John Otieno"},
        format="json",
    )
    awards = named.json()["awards"]
    assert [a["title"] for a in awards[-2:]] == ["Fair play", "Best umpire"]
    assert awards[-1]["receives"] == "John Otieno"
    placement = awards[0]["id"]
    assert (
        staff.patch(
            ceremony_url(game, f"awards/{placement}/"), {"recipient_name": "Someone"}, format="json"
        ).status_code
        == 409
    )

    # Players don't see a draft, and only competition staff run it.
    winner_client = logged_in(winner_user)
    assert winner_client.get(ceremony_url(game)).status_code == 404
    assert winner_client.post(ceremony_url(game, "publish/"), format="json").status_code == 403

    # The main award last: move Fair play to the end.
    ids = [a["id"] for a in awards]
    moved = ids[:-2] + [ids[-1], ids[-2]]
    assert staff.post(ceremony_url(game, "reorder/"), {"awards": ids[:-1]}, format="json").status_code == 400
    reordered = staff.post(ceremony_url(game, "reorder/"), {"awards": moved}, format="json").json()
    assert [a["title"] for a in reordered["awards"]][-1] == "Fair play"

    assert (
        staff.post(ceremony_url(game, f"awards/{ids[0]}/present/"), format="json").status_code == 409
    )  # a draft
    published = staff.post(ceremony_url(game, "publish/"), format="json").json()
    assert published["status"] == "published" and published["location"] == "Main hall"
    seen = winner_client.get(ceremony_url(game)).json()
    assert [a["title"] for a in seen["awards"]] == [a["title"] for a in reordered["awards"]]

    for award_id in moved:
        last = staff.post(ceremony_url(game, f"awards/{award_id}/present/"), format="json").json()
    assert last["status"] == "done" and all(a["presented_at"] for a in last["awards"])
    honours = winner_client.get("/api/v1/me/honours/").json()
    assert {h["title"] for h in honours} == {"Singles: Winner", "Fair play"}
    assert set(honours[0]) == {"id", "title", "place", "prize", "tournament", "tournament_name", "held_on"}

    # Generating again keeps what was presented.
    again = staff.post(ceremony_url(game, "generate/"), format="json").json()["awards"]
    assert len(again) == 6


def test_a_draft_tournament_has_no_ceremony(staff, club, hall):  # noqa: F811
    from .test_tournaments import add_event, make_tournament

    draft = add_event(staff, make_tournament(staff, club, hall))
    response = staff.put(f"/api/v1/tournaments/{draft['id']}/ceremony/", {"location": "Hall"}, format="json")
    assert response.status_code == 409
