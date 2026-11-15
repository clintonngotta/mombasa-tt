import pytest

from .conftest import BrowserClient
from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db
URL = "/api/v1/me/matches/"


def payload(**overrides):
    data = {
        "played_on": "2026-10-01",
        "label": "Friendly",
        "format": "singles",
        "opponent_name": "J. Otieno",
        "games": [
            {"my_points": 11, "opponent_points": 7},
            {"my_points": 9, "opponent_points": 11},
            {"my_points": 11, "opponent_points": 5},
        ],
        "notes": "Backhand flick worked; serve receive was loose.",
    }
    return {**data, **overrides}


@pytest.fixture
def ama(db):
    return make_user("ama@example.com")


@pytest.fixture
def ama_client(ama):
    return logged_in(ama)


def test_create_derives_result_from_sets(ama_client):
    res = ama_client.post(URL, payload(), format="json")
    assert res.status_code == 201, res.json()
    body = res.json()
    assert (body["games_won"], body["games_lost"], body["result"]) == (2, 1, "win")
    assert [g["my_points"] for g in body["games"]] == [11, 9, 11]


@pytest.mark.parametrize(
    "games, message_field",
    [
        ([], "games"),
        ([{"my_points": 11, "opponent_points": 11}], "games"),
        ([{"my_points": -1, "opponent_points": 11}], "games"),
        ([{"my_points": 11, "opponent_points": 3}] * 8, "games"),
    ],
)
def test_invalid_sets_are_rejected_with_field_errors(ama_client, games, message_field):
    res = ama_client.post(URL, payload(games=games), format="json")
    assert res.status_code == 400
    assert message_field in res.json()["fields"]


def test_label_is_free_text_and_required(ama_client):
    assert ama_client.post(URL, payload(label="Sunday ladder @ Coast"), format="json").status_code == 201
    assert "label" in ama_client.post(URL, payload(label="  "), format="json").json()["fields"]


def test_singles_drops_partner_name(ama_client):
    res = ama_client.post(URL, payload(partner_name="Someone"), format="json")
    assert res.json()["partner_name"] == ""
    res = ama_client.post(URL, payload(format="doubles", partner_name="K. Mwangi"), format="json")
    assert res.json()["partner_name"] == "K. Mwangi"


def test_update_replaces_sets(ama_client):
    match_id = ama_client.post(URL, payload(), format="json").json()["id"]
    res = ama_client.patch(
        f"{URL}{match_id}/", {"games": [{"my_points": 5, "opponent_points": 11}]}, format="json"
    )
    assert res.status_code == 200
    assert (res.json()["games_won"], res.json()["result"]) == (0, "loss")


def test_only_the_owner_can_see_or_touch_a_record(ama, ama_client):
    match_id = ama_client.post(URL, payload(), format="json").json()["id"]
    others = {
        "another player": logged_in(make_user("kofi@example.com")),
        "platform staff": logged_in(make_user("ops@example.com", is_staff=True, is_superuser=True)),
    }
    for who, client in others.items():
        assert client.get(URL).json()["count"] == 0, who
        assert client.get(f"{URL}{match_id}/").status_code == 404, who
        assert client.patch(f"{URL}{match_id}/", {"notes": "x"}, format="json").status_code == 404, who
        assert client.delete(f"{URL}{match_id}/").status_code == 404, who
        assert client.get(f"{URL}stats/").json()["played"] == 0, who
    assert BrowserClient().get(URL).status_code == 401
    assert ama_client.get(f"{URL}{match_id}/").json()["notes"].startswith("Backhand")


def test_list_filters_by_label_case_insensitively(ama_client):
    ama_client.post(URL, payload(label="Tournament"), format="json")
    ama_client.post(URL, payload(label="Friendly"), format="json")
    res = ama_client.get(URL, {"label": "tournament"})
    assert [m["label"] for m in res.json()["results"]] == ["Tournament"]


def test_stats_summarise_only_own_records(ama_client):
    lost = [{"my_points": 3, "opponent_points": 11}]
    ama_client.post(URL, payload(label="Friendly", played_on="2026-09-01"), format="json")
    ama_client.post(URL, payload(label="Friendly", played_on="2026-09-02", games=lost), format="json")
    ama_client.post(URL, payload(label="Tournament", played_on="2026-09-03"), format="json")

    stats = ama_client.get(f"{URL}stats/").json()
    assert (stats["played"], stats["won"], stats["lost"], stats["drawn"]) == (3, 2, 1, 0)
    assert stats["win_rate"] == pytest.approx(0.667)
    assert stats["recent_form"] == ["win", "loss", "win"]
    assert {r["label"]: r["played"] for r in stats["by_label"]} == {"Friendly": 2, "Tournament": 1}
    assert ama_client.get(f"{URL}stats/", {"label": "friendly"}).json()["played"] == 2


def test_labels_offer_own_labels_then_suggestions(ama_client):
    ama_client.post(URL, payload(label="Ladder"), format="json")
    ama_client.post(URL, payload(label="Ladder"), format="json")
    ama_client.post(URL, payload(label="Friendly"), format="json")
    labels = ama_client.get(f"{URL}labels/").json()["labels"]
    assert labels[:2] == ["Ladder", "Friendly"]
    assert "Tournament" in labels and labels.count("Friendly") == 1


def test_delete(ama_client):
    match_id = ama_client.post(URL, payload(), format="json").json()["id"]
    assert ama_client.delete(f"{URL}{match_id}/").status_code == 204
    assert ama_client.get(f"{URL}{match_id}/").status_code == 404
