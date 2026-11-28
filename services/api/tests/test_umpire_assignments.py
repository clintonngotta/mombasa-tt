"""An umpire's own matches (REQ-012, REQ-019): told when staff give them a match or take it away, and one
page with what is still to score and what they have confirmed."""

from datetime import timedelta

import pytest
from django.utils import timezone

from competitions.models import Match
from notifications.models import Notification, Preference

from .helpers import logged_in, make_user
from .test_roles import add_member
from .test_umpire_scoring import START, Deck, assign, final, match_url, point, scorers, umpire  # noqa: F401

pytestmark = pytest.mark.django_db
MINE = "/api/v1/me/scorecards/"


def alerts(user) -> list[tuple[str, str, bool]]:
    rows = Notification.objects.filter(recipient=user, category="umpiring").order_by("created_at")
    return [(alert.title, alert.link, alert.superseded) for alert in rows]


def test_the_umpire_is_told_when_given_a_match_and_when_it_is_taken_away(staff, club, final, umpire):  # noqa: F811
    other = make_user("second-umpire@example.com", display_name="Second Umpire")
    add_member(club, other, scorers(club))
    a, b = (final["match"].entry_a.players.get().user, final["match"].entry_b.players.get().user)
    sides = f"{a.display_name} v {b.display_name}"

    assign(staff, final, umpire)
    [(title, link, _)] = alerts(umpire)
    assert (title, link) == (f"You're umpiring {sides}", "/umpiring")
    alert = Notification.objects.get(recipient=umpire, category="umpiring")
    assert final["cup"]["name"] in alert.body and "Singles" in alert.body and "Final" in alert.body

    # Assigned again to the same umpire (a new device): nothing new to tell.
    assign(staff, final, umpire)
    assert len(alerts(umpire)) == 1

    # Given to someone else: the new umpire is told, and the first one that it's gone.
    assign(staff, final, other)
    assert [title for title, _, _ in alerts(other)] == [f"You're umpiring {sides}"]
    assert alerts(umpire) == [
        (f"You're umpiring {sides}", "/umpiring", True),
        (f"You no longer umpire {sides}", "/umpiring", False),
    ]

    # Taken back to nobody.
    assign(staff, final, None)
    assert alerts(other)[-1][0] == f"You no longer umpire {sides}"
    # The players hear nothing about who umpires.
    assert not Notification.objects.filter(recipient__in=[a, b], category="umpiring").exists()


def test_no_alert_for_assigning_yourself_or_with_umpiring_alerts_off(staff, admin, final, umpire):  # noqa: F811
    assign(staff, final, admin)  # staff take the match themselves
    assert alerts(admin) == []

    Preference.objects.create(user=umpire, category="umpiring")
    assign(staff, final, umpire)
    assert alerts(umpire) == []
    # Staff took it from themselves: they are not told either.
    assert alerts(admin) == []


def test_the_umpire_page_lists_what_is_to_score_and_what_was_confirmed(staff, final, umpire):  # noqa: F811
    as_umpire = logged_in(umpire)
    assert as_umpire.get(MINE, {"state": "done"}).json()["results"] == []
    assert as_umpire.get(MINE, {"state": "everything"}).status_code == 400

    start = timezone.now() + timedelta(hours=2)
    Match.objects.filter(pk=final["match"].pk).update(scheduled_at=start)
    assign(staff, final, umpire)
    [open_card] = as_umpire.get(MINE).json()["results"]
    assert as_umpire.get(MINE, {"state": "open"}).json()["results"] == [open_card]
    assert open_card["scheduled_at"] is not None and open_card["planned_table"] == ""
    assert open_card["status"] == "assigned"

    deck = Deck(as_umpire, open_card["id"])
    deck.send(START, *[point("a")] * 22)
    deck.confirm()

    assert as_umpire.get(MINE).json()["results"] == []
    [done] = as_umpire.get(MINE, {"state": "done"}).json()["results"]
    assert (done["id"], done["status"], done["label"]) == (open_card["id"], "confirmed", "Final")
    assert done["confirmed_at"]
    # Somebody else's record isn't theirs to see.
    assert staff.get(MINE, {"state": "done"}).json()["results"] == []
    assert logged_in(make_user("nosy@example.com")).get(MINE, {"state": "done"}).json()["results"] == []
