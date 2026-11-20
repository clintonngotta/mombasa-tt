"""Quick Score saves (REQ-017, EVAL-017): casual, labelled as recorded by the player, saved once."""

import uuid

import pytest

from competitions.models import Match, OfficialResult
from matchlog.models import PersonalMatch
from ratings.models import Rating, RatingEvent
from reservations.models import Reservation

from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db
URL = "/api/v1/me/matches/"


def quick(ref, **overrides):
    return {
        "played_on": "2026-11-19",
        "label": "Quick Score",
        "format": "singles",
        "opponent_name": "Player B",
        "partner_name": "",
        "venue": "",
        "notes": "",
        "games": [{"my_points": 11, "opponent_points": 8}, {"my_points": 11, "opponent_points": 9}],
        "source": "quick_score",
        "client_ref": str(ref),
        **overrides,
    }


def competitive():
    return [m.objects.count() for m in (Rating, RatingEvent, Reservation, OfficialResult, Match)]


def test_a_retried_save_returns_the_record_already_made():
    amina = logged_in(make_user("amina@example.com"))
    ref = uuid.uuid4()
    before = competitive()
    first = amina.post(URL, quick(ref), format="json")
    assert first.status_code == 201, first.json()
    assert (first.json()["source"], first.json()["client_ref"]) == ("quick_score", str(ref))
    again = amina.post(URL, quick(ref, opponent_name="Changed on retry"), format="json")
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["opponent_name"] == "Player B"
    assert PersonalMatch.objects.count() == 1
    # Casual: nothing competitive moves.
    assert competitive() == before


def test_the_same_device_id_is_separate_per_player():
    ref = uuid.uuid4()
    amina = logged_in(make_user("amina@example.com"))
    brian = logged_in(make_user("brian@example.com"))
    a = amina.post(URL, quick(ref), format="json").json()
    b = brian.post(URL, quick(ref), format="json")
    assert b.status_code == 201
    assert b.json()["id"] != a["id"]
    assert PersonalMatch.objects.filter(client_ref=ref).count() == 2


def test_editing_keeps_how_the_record_was_made():
    amina = logged_in(make_user("amina@example.com"))
    ref = uuid.uuid4()
    made = amina.post(URL, quick(ref), format="json").json()
    changed = amina.patch(
        f"{URL}{made['id']}/",
        {"venue": "Coast Hall", "source": "manual", "client_ref": str(uuid.uuid4())},
        format="json",
    ).json()
    assert changed["venue"] == "Coast Hall"
    assert (changed["source"], changed["client_ref"]) == ("quick_score", str(ref))


def test_a_hand_entered_match_is_manual_and_signed_out_saves_are_refused(client):
    amina = logged_in(make_user("amina@example.com"))
    body = quick(uuid.uuid4())
    del body["source"], body["client_ref"]
    made = amina.post(URL, body, format="json").json()
    assert (made["source"], made["client_ref"]) == ("manual", None)
    assert client.post(URL, quick(uuid.uuid4()), format="json").status_code in (401, 403)
    assert PersonalMatch.objects.count() == 1


def test_a_bad_device_id_is_a_validation_error():
    amina = logged_in(make_user("amina@example.com"))
    response = amina.post(URL, quick("not-a-uuid"), format="json")
    assert response.status_code == 400
    assert "client_ref" in response.json()["fields"]
