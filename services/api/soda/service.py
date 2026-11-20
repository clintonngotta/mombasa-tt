"""The rules of a soda game (REQ-040, TASK-076)."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.exceptions import ApiException
from organizations.models import Membership
from profiles.models import listed_profiles

from .models import Challenge, Policy, Result


def gate_open() -> bool:
    """Stakes need the recorded legal and policy sign-off (TASK-078) before they can be switched on."""
    return bool(getattr(settings, "SODA_STAKES_ENABLED", False))


def _clubs(user):
    return Membership.objects.active().filter(user=user).values_list("organization_id", flat=True)


def _policies(*users):
    clubs = set()
    for user in users:
        clubs.update(_clubs(user))
    return Policy.objects.filter(organization_id__in=clubs)


def games_allowed(*users) -> bool:
    return not _policies(*users).filter(games_enabled=False).exists()


def stakes_allowed(*users) -> bool:
    return gate_open() and not _policies(*users).filter(stakes_enabled=False).exists()


def reachable(challenger, other) -> bool:
    """A player can challenge someone in one of their clubs, or anyone listed in the player directory."""
    if not other.is_active or other.pk == challenger.pk:
        return False
    shared = Membership.objects.active().filter(user=other, organization_id__in=_clubs(challenger)).exists()
    return shared or listed_profiles().filter(user=other).exists()


def check_new(challenger, challenged, staked: bool) -> None:
    if not reachable(challenger, challenged):
        raise ApiException("not_reachable", "You can challenge club mates and players in the directory.", 400)
    if not games_allowed(challenger, challenged):
        raise ApiException("soda_disabled", "A club of one of the players has switched soda games off.", 409)
    if staked and not stakes_allowed(challenger, challenged):
        raise ApiException("stakes_disabled", "Stakes aren't available for this challenge.", 409)


def _locked(challenge: Challenge) -> Challenge:
    return Challenge.objects.select_for_update().get(pk=challenge.pk)


def _only(user, challenge: Challenge, who: str) -> None:
    if getattr(challenge, f"{who}_id") != user.pk:
        raise ApiException("not_yours", "Only the other player can do that.", 403)


def _open(challenge: Challenge, *statuses) -> None:
    if challenge.status not in statuses:
        raise ApiException("challenge_closed", "This challenge can't be answered that way now.", 409)


@transaction.atomic
def accept(challenge: Challenge, user, match_stake: bool) -> Challenge:
    challenge = _locked(challenge)
    if challenge.status == Challenge.Status.ACCEPTED and user.pk == challenge.challenged_id:
        return challenge
    if challenge.status == Challenge.Status.COUNTERED:
        # The challenger takes the time the challenged player proposed.
        _only(user, challenge, "challenger")
        challenge.play_at = challenge.proposed_at
    else:
        _open(challenge, Challenge.Status.PENDING)
        _only(user, challenge, "challenged")
        if match_stake:
            if not challenge.staked:
                raise ApiException("no_stake", "The challenge has no stake to match.", 400)
            if not stakes_allowed(challenge.challenger, challenge.challenged):
                raise ApiException("stakes_disabled", "Stakes aren't available for this challenge.", 409)
            challenge.challenged_staked = True
    challenge.status = Challenge.Status.ACCEPTED
    challenge.answered_at = timezone.now()
    challenge.save()
    return challenge


@transaction.atomic
def counter(challenge: Challenge, user, play_at) -> Challenge:
    challenge = _locked(challenge)
    _open(challenge, Challenge.Status.PENDING, Challenge.Status.COUNTERED)
    _only(user, challenge, "challenged")
    challenge.proposed_at = play_at
    challenge.status = Challenge.Status.COUNTERED
    challenge.answered_at = timezone.now()
    challenge.save()
    return challenge


@transaction.atomic
def decline(challenge: Challenge, user) -> Challenge:
    challenge = _locked(challenge)
    _open(challenge, Challenge.Status.PENDING, Challenge.Status.COUNTERED)
    _only(user, challenge, "challenged")
    challenge.status = Challenge.Status.DECLINED
    challenge.answered_at = timezone.now()
    challenge.save()
    return challenge


@transaction.atomic
def withdraw(challenge: Challenge, user) -> Challenge:
    challenge = _locked(challenge)
    _open(challenge, Challenge.Status.PENDING, Challenge.Status.COUNTERED)
    _only(user, challenge, "challenger")
    challenge.status = Challenge.Status.WITHDRAWN
    challenge.save()
    return challenge


def valid_games(games, best_of: int) -> list[list[int]]:
    needed = best_of // 2 + 1
    challenger = challenged = 0
    for a, b in games:
        if challenger == needed or challenged == needed:
            raise ApiException("bad_result", "Games are listed after the match was already won.", 400)
        high, low = max(a, b), min(a, b)
        if high < 11 or (high > 11 and high - low != 2) or (high == 11 and low > 9):
            raise ApiException("bad_result", f"{a}-{b} isn't a finished game to 11.", 400)
        challenger += a > b
        challenged += b > a
    if needed not in (challenger, challenged):
        raise ApiException("bad_result", f"Best of {best_of} needs {needed} games won.", 400)
    return [list(game) for game in games]


@transaction.atomic
def record(challenge: Challenge, user, games) -> Result:
    """Record (or correct, until both have confirmed) the games. The recorder confirms by recording."""
    challenge = _locked(challenge)
    if user.pk not in (challenge.challenger_id, challenge.challenged_id):
        raise ApiException("not_yours", "Only the two players record the result.", 403)
    _open(challenge, Challenge.Status.ACCEPTED, Challenge.Status.PLAYED)
    games = valid_games(games, challenge.best_of)
    result = Result.objects.select_for_update().filter(challenge=challenge).first()
    if result is not None and result.confirmed:
        raise ApiException("result_confirmed", "Both players confirmed this result.", 409)
    mine = "challenger" if user.pk == challenge.challenger_id else "challenged"
    fields = {
        "games": games,
        "recorded_by": user,
        "challenger_confirmed": mine == "challenger",
        "challenged_confirmed": mine == "challenged",
        "disputed_by": None,
        "dispute_reason": "",
    }
    if result is None:
        result = Result.objects.create(challenge=challenge, **fields)
    else:
        for key, value in fields.items():
            setattr(result, key, value)
        result.save()
    challenge.status = Challenge.Status.PLAYED
    challenge.save(update_fields=["status"])
    return result


def _result_for(challenge: Challenge, user) -> Result:
    if user.pk not in (challenge.challenger_id, challenge.challenged_id):
        raise ApiException("not_yours", "Only the two players answer for the result.", 403)
    result = Result.objects.select_for_update().filter(challenge=challenge).first()
    if result is None:
        raise ApiException("no_result", "No result has been recorded yet.", 409)
    return result


@transaction.atomic
def confirm(challenge: Challenge, user) -> Result:
    result = _result_for(challenge, user)
    if result.disputed_by_id:
        raise ApiException("result_disputed", "Record the result again to settle the dispute.", 409)
    if user.pk == challenge.challenger_id:
        result.challenger_confirmed = True
    else:
        result.challenged_confirmed = True
    result.save()
    return result


@transaction.atomic
def dispute(challenge: Challenge, user, reason: str) -> Result:
    result = _result_for(challenge, user)
    if result.confirmed:
        raise ApiException("result_confirmed", "Both players confirmed this result.", 409)
    result.disputed_by = user
    result.dispute_reason = reason
    result.challenger_confirmed = result.challenged_confirmed = False
    result.save()
    return result


def outcome(challenge: Challenge) -> dict:
    """Who won and who owes what. Nothing is owed until both confirmed, nor while disputed; only a
    loser who pledged owes, and only what they pledged."""
    result = getattr(challenge, "result", None)
    if result is None:
        return {"state": "not_played", "winner_id": None, "owed_by_id": None}
    if result.disputed_by_id:
        return {"state": "disputed", "winner_id": None, "owed_by_id": None}
    if not result.confirmed:
        return {"state": "awaiting_confirmation", "winner_id": None, "owed_by_id": None}
    won, lost = result.tally()
    winner, loser = (
        (challenge.challenger_id, challenge.challenged_id)
        if won > lost
        else (challenge.challenged_id, challenge.challenger_id)
    )
    pledged = challenge.staked and (loser == challenge.challenger_id or challenge.challenged_staked)
    return {
        "state": "settled" if result.settled_at else "confirmed",
        "winner_id": winner,
        "owed_by_id": loser if pledged else None,
    }


@transaction.atomic
def settle(challenge: Challenge, user) -> Result:
    """The winner marks the pledge honoured. Coast TT records only that it was settled."""
    result = _result_for(challenge, user)
    state = outcome(challenge)
    if state["owed_by_id"] is None:
        raise ApiException("nothing_owed", "Nothing is owed on this result.", 409)
    if state["winner_id"] != user.pk:
        raise ApiException("not_yours", "The winner marks the pledge settled.", 403)
    if result.settled_at is None:
        result.settled_at = timezone.now()
        result.save(update_fields=["settled_at", "updated_at"])
    return result
