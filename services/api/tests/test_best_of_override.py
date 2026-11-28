"""A platform super admin says how many games a match was really played over (user request, 2026-11-28).

When an event moved from best of 3 to best of 5 part-way, matches already decided or on a table kept
best of 3. If one of them was in fact played over five games, a super admin enters or corrects its
result with `best_of`; the score is checked against it and it stays the match's best of.
"""

import pytest

from competitions.models import MatchDayLog

from .helpers import logged_in, make_user
from .test_official_results import correct, enter, fresh, hall, knockout  # noqa: F401
from .test_reservations import send, tables
from .test_tournaments import url

pytestmark = pytest.mark.django_db

THREE_ONE = [[11, 5], [9, 11], [11, 7], [11, 8]]  # a best-of-5 win
TWO_NIL = [[11, 5], [11, 7]]  # a best-of-3 win


def super_admin():
    user = make_user("root@example.com", display_name="Platform Admin")
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    return logged_in(user)


def moved_to_five(staff, club, hall):  # noqa: F811
    """Best of 3, one semi-final decided and the other on its table, then the event goes to best of 5:
    both semi-finals keep best of 3."""
    game = knockout(staff, club, hall, best_of=3)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=TWO_NIL)
    send(staff, {**game, "match": second}, tables(hall)[0])
    changed = staff.patch(url(game["cup"], event=game["event"]), {"best_of": 5}, format="json")
    assert changed.status_code == 200, changed.json()
    assert (fresh(first).best_of, fresh(second).best_of) == (3, 3)
    return game, first, second


def test_a_super_admin_corrects_a_match_that_was_really_best_of_five(staff, club, hall):  # noqa: F811
    game, first, _ = moved_to_five(staff, club, hall)
    admin = super_admin()
    # As a best of 3 the four-game score doesn't fit.
    assert (
        correct(admin, game, fresh(first), first.entry_a, expect=400, games=THREE_ONE)["code"]
        == "invalid_result"
    )

    correct(admin, game, fresh(first), first.entry_a, games=THREE_ONE, best_of=5, reason="Played over five")

    decided = fresh(first)
    assert (decided.best_of, decided.games, decided.winner_id) == (5, THREE_ONE, first.entry_a_id)
    log = MatchDayLog.objects.get(action="result_corrected", match=first)
    assert "played over best of 5, not 3" in log.summary and log.reason == "Played over five"
    page = admin.get(url(game["cup"], event=game["event"]) + f"matches/{first.id}/").json()
    assert page["best_of"] == 5 and page["can_change_best_of"] is True


def test_a_super_admin_enters_a_match_on_its_table_at_its_real_length(staff, club, hall):  # noqa: F811
    game, _, second = moved_to_five(staff, club, hall)
    enter(super_admin(), game, fresh(second), second.entry_b, games=[[b, a] for a, b in THREE_ONE], best_of=5)
    assert (fresh(second).best_of, fresh(second).winner_id) == (5, second.entry_b_id)


def test_only_a_super_admin_changes_how_many_games_a_match_was_played_over(staff, club, hall):  # noqa: F811
    game, first, _ = moved_to_five(staff, club, hall)
    refused = correct(staff, game, fresh(first), first.entry_a, expect=403, games=THREE_ONE, best_of=5)
    assert refused["code"] == "super_admin_only"
    assert fresh(first).best_of == 3 and fresh(first).games == TWO_NIL
    # Naming the length it already has is no change, so anyone entering results may send it.
    correct(staff, game, fresh(first), first.entry_b, games=[[5, 11], [7, 11]], best_of=3)
    page = staff.get(url(game["cup"], event=game["event"]) + f"matches/{first.id}/").json()
    assert page["can_change_best_of"] is False
