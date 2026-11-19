"""Private match notes (REQ-025, EVAL-025)."""

import pytest

from matchlog.models import MatchNote, PersonalMatch

from .helpers import logged_in, make_user
from .test_reservations import person, started
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db

NOTES = "/api/v1/me/match-notes/"


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    return venue


@pytest.fixture
def game(staff, club, hall):
    return started(staff, club, hall, [["Amina"], ["Brian"]])


def note_on(client, expect=201, **body):
    response = client.post(NOTES, body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_a_player_keeps_private_notes_on_their_official_match(staff, game):
    amina = logged_in(person("Amina"))
    match = game["match"]
    before = (match.status, match.winner_id, match.entry_a_id, match.entry_b_id)
    made = note_on(amina, match_id=str(match.id), observations="Short serves worked", goals="Backhand flick")
    assert (made["kind"], made["tournament_id"]) == ("official", game["cup"]["id"])
    assert made["title"] in {"Amina v Brian", "Brian v Amina"}
    assert made["event_id"] == game["event"]["id"] and made["tournament_name"] == "Coast Open"
    changed = amina.patch(f"{NOTES}{made['id']}/", {"goals": "Third-ball attack"}, format="json").json()
    assert (changed["observations"], changed["goals"]) == ("Short serves worked", "Third-ball attack")
    # Editing can't move the note to another match, and nothing about the match itself changes.
    amina.patch(f"{NOTES}{made['id']}/", {"match_id": None, "personal_match_id": None}, format="json")
    assert MatchNote.objects.get().match_id == match.id
    match.refresh_from_db()
    assert (match.status, match.winner_id, match.entry_a_id, match.entry_b_id) == before
    found = amina.get(NOTES, {"match": str(match.id)}).json()["results"]
    assert [n["id"] for n in found] == [made["id"]]
    assert note_on(amina, expect=409, match_id=str(match.id))["code"] == "note_exists"
    assert amina.delete(f"{NOTES}{made['id']}/").status_code == 204
    assert not MatchNote.objects.exists()


def test_nobody_else_reads_or_touches_a_note_opponent_staff_or_outsider(staff, game):
    amina = logged_in(person("Amina"))
    made = note_on(amina, match_id=str(game["match"].id), observations="MARK-PRIVATE")
    for other in (logged_in(person("Brian")), staff, logged_in(make_user("outsider@example.com"))):
        assert other.get(NOTES).json()["results"] == []
        assert other.get(NOTES, {"match": str(game["match"].id)}).json()["results"] == []
        assert other.get(f"{NOTES}{made['id']}/").status_code == 404
        assert other.patch(f"{NOTES}{made['id']}/", {"goals": "x"}, format="json").status_code == 404
        assert other.delete(f"{NOTES}{made['id']}/").status_code == 404
    # The match's public pages carry no note.
    match = (
        f"/api/v1/tournaments/{game['cup']['id']}/events/{game['event']['id']}/matches/{game['match'].id}/"
    )
    assert "MARK-PRIVATE" not in staff.get(match).content.decode()
    assert MatchNote.objects.get().goals == ""


def test_notes_only_on_a_match_you_played_or_recorded(staff, game):
    outsider = logged_in(make_user("outsider@example.com"))
    assert outsider.post(NOTES, {"match_id": str(game["match"].id)}, format="json").status_code == 404
    assert staff.post(NOTES, {"match_id": str(game["match"].id)}, format="json").status_code == 404
    brian = person("Brian")
    theirs = PersonalMatch.objects.create(owner=brian, played_on="2026-11-01", label="Friendly")
    amina = logged_in(person("Amina"))
    assert amina.post(NOTES, {"personal_match_id": str(theirs.id)}, format="json").status_code == 404
    assert "match_id" in note_on(amina, expect=400)["fields"]
    both = note_on(amina, expect=400, match_id=str(game["match"].id), personal_match_id=str(theirs.id))
    assert "match_id" in both["fields"]
    own = PersonalMatch.objects.create(
        owner=brian, played_on="2026-11-02", label="Practice", opponent_name="Chege"
    )
    made = note_on(logged_in(brian), personal_match_id=str(own.id), observations="Loops too high")
    assert (made["kind"], made["title"], made["tournament_id"]) == ("own", "Practice v Chege", None)
