"""Watch links for a tournament and its matches (REQ-042)."""

import pytest

from competitions.models import LiveStream, LiveStreamReport, Match

from .helpers import logged_in, make_user
from .test_reservations import started
from .test_tournaments import make_tournament
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    return venue


@pytest.fixture
def game(staff, club, hall):
    return started(staff, club, hall, [["Amina"], ["Brian"]])


def streams(cup_id) -> str:
    return f"/api/v1/tournaments/{cup_id}/streams/"


def add(client, cup_id, expect=201, **body):
    response = client.post(streams(cup_id), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


@pytest.mark.parametrize(
    ("url", "platform", "domain"),
    [
        ("https://www.youtube.com/live/abc123", "youtube", "youtube.com"),
        ("https://youtu.be/abc123", "youtube", "youtu.be"),
        ("https://m.facebook.com/coasttt/videos/1", "facebook", "m.facebook.com"),
        ("https://fb.watch/xyz/", "facebook", "fb.watch"),
        ("https://www.instagram.com/coasttt/live/", "instagram", "instagram.com"),
        ("https://www.tiktok.com/@coasttt/live", "tiktok", "tiktok.com"),
        ("https://www.twitch.tv/coasttt", "twitch", "twitch.tv"),
        ("https://x.com/coasttt/status/1", "x", "x.com"),
        ("https://kick.com/coasttt", "kick", "kick.com"),
        ("https://stream.coasttt.co.ke/court-1", "other", "stream.coasttt.co.ke"),
    ],
)
def test_staff_add_links_from_any_site_named_by_where_they_go(staff, game, url, platform, domain):
    shown = add(staff, game["cup"]["id"], url=url, title="Centre court")
    assert (shown["platform"], shown["domain"], shown["url"], shown["match_id"]) == (
        platform,
        domain,
        url,
        None,
    )
    assert shown["report_count"] == 0


@pytest.mark.parametrize(
    ("url", "says"),
    [
        ("http://www.youtube.com/live/abc", "https"),
        ("javascript:alert(1)", "https"),
        ("https://localhost/stream", "public website"),
        ("https://10.0.0.5/stream", "number address"),
        ("https://[::1]/stream", "public website"),
        ("https://192.168.1.4.nip/x", None),  # a name, allowed: it is shown as is
        ("https://user:pw@youtube.com/live", "password"),
        ("https://youtube.com:8443/live", "port"),
        ("https://youtube.com.evil.example/live", None),
        ("not a link", "https"),
    ],
)
def test_a_link_must_be_https_on_a_public_site(staff, game, url, says):
    if says is None:
        shown = add(staff, game["cup"]["id"], url=url)
        assert shown["platform"] == "other"  # youtube.com.evil.example is not YouTube
        return
    reply = add(staff, game["cup"]["id"], expect=400, url=url)
    assert says in str(reply["fields"]["url"])


def test_a_match_has_its_own_links_and_shows_the_tournaments_too(staff, game):
    cup = game["cup"]["id"]
    whole = add(staff, cup, url="https://www.youtube.com/live/all-day")
    court = add(staff, cup, url="https://www.tiktok.com/@club/live", match_id=str(game["match"].id))
    assert court["match_id"] == str(game["match"].id)
    viewer = logged_in(make_user("fan@example.com"))
    assert [s["id"] for s in viewer.get(streams(cup)).json()] == [whole["id"], court["id"]]
    other = Match.objects.exclude(pk=game["match"].pk).filter(draw__event__tournament_id=cup).first()
    for_match = viewer.get(streams(cup), {"match": str(game["match"].id)}).json()
    assert [s["id"] for s in for_match] == [whole["id"], court["id"]]
    if other:
        assert [s["id"] for s in viewer.get(streams(cup), {"match": str(other.id)}).json()] == [whole["id"]]
    assert viewer.get(streams(cup), {"match": "nonsense"}).status_code == 404
    # The same link twice in one place is refused.
    assert add(staff, cup, expect=409, url="https://www.youtube.com/live/all-day")["code"] == "stream_exists"


def test_a_match_of_another_tournament_is_refused(staff, club, hall, game):
    other = started(staff, club, hall, [["Chege"], ["Daudi"]], tournament="Second Open")
    reply = add(
        staff, game["cup"]["id"], expect=400, url="https://kick.com/x", match_id=str(other["match"].id)
    )
    assert "match_id" in reply["fields"]


def test_only_the_hosts_staff_add_change_and_remove_links(staff, game):
    cup = game["cup"]["id"]
    made = add(staff, cup, url="https://www.youtube.com/live/abc")
    viewer = logged_in(make_user("fan@example.com"))
    assert viewer.post(streams(cup), {"url": "https://kick.com/x"}, format="json").status_code == 403
    assert viewer.patch(f"{streams(cup)}{made['id']}/", {"title": "x"}, format="json").status_code == 403
    assert viewer.delete(f"{streams(cup)}{made['id']}/").status_code == 403
    changed = staff.patch(f"{streams(cup)}{made['id']}/", {"url": "https://fb.watch/new"}, format="json")
    assert (changed.json()["platform"], changed.json()["url"]) == ("facebook", "https://fb.watch/new")
    assert (
        staff.patch(f"{streams(cup)}{made['id']}/", {"url": "http://x.com"}, format="json").status_code == 400
    )
    assert staff.delete(f"{streams(cup)}{made['id']}/").status_code == 204
    assert not LiveStream.objects.exists()


def test_a_draft_has_no_links_and_its_links_are_the_hosts_secret(staff, club, hall):
    draft = make_tournament(staff, club, hall)
    assert add(staff, draft["id"], expect=409, url="https://kick.com/x")["code"] == "not_streamable"
    viewer = logged_in(make_user("fan@example.com"))
    assert viewer.get(streams(draft["id"])).status_code == 404
    assert staff.get(streams(draft["id"])).json() == []


def test_viewers_report_a_link_once_and_only_staff_see_the_count(staff, game):
    cup = game["cup"]["id"]
    made = add(staff, cup, url="https://www.youtube.com/live/abc")
    fan, other = logged_in(make_user("fan@example.com")), logged_in(make_user("other@example.com"))
    report = f"{streams(cup)}{made['id']}/report/"
    assert fan.post(report, {"reason": "broken"}, format="json").status_code == 204
    assert fan.post(report, {"reason": "inappropriate", "note": "Not ours"}, format="json").status_code == 204
    assert other.post(report, {"reason": "wrong"}, format="json").status_code == 204
    assert fan.post(report, {"reason": "spam"}, format="json").status_code == 400
    assert LiveStreamReport.objects.count() == 2
    assert LiveStreamReport.objects.get(note="Not ours").reason == "inappropriate"
    assert fan.get(streams(cup)).json()[0]["report_count"] is None
    assert staff.get(streams(cup)).json()[0]["report_count"] == 2
    assert (
        fan.post(
            f"/api/v1/tournaments/{cup}/streams/{game['cup']['id']}/report/",
            {"reason": "broken"},
            format="json",
        ).status_code
        == 404
    )
