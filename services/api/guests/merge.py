"""Moving a claimed guest onto the claimant's account (REQ-003).

Everything that points at the guest's user (entries, matches, results, check-ins, notes) is pointed at
the claimant instead, so match references stay what they were: the same rows, now the claimant's. It
happens all at once or not at all. Where the claimant already holds what the guest holds, and the
database refuses two of it (both entered in one event, both in one team match), nothing moves and the
clashes are reported for staff to resolve.

Ratings are not moved: they are worked out again from the official results by the outbox worker once
the results are the claimant's.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from outbox import service as outbox
from ratings import service as ratings
from ratings.models import Discipline, Rating, RatingEvent

User = get_user_model()

RERATE = "guests.rerate"

# What a clash means, in the words staff read. Anything else is named by its model.
CLASH_WORDS = {
    ("competitions", "entryplayer"): "Both are entered in the same event",
    ("competitions", "rubberplayer"): "Both play in the same team match",
    ("organizations", "membership"): "Both are members of the same club",
    ("profiles", "profile"): "Both have a player profile",
}

# Kept with the guest: its own record, and ratings, which are worked out again instead.
SKIPPED = {"guests", "sessions"}
RECOMPUTED = {Rating, RatingEvent}


class Clash(Exception):
    def __init__(self, clashes: list[str]):
        super().__init__(", ".join(clashes))
        self.clashes = clashes


def _references():
    """Every column, in any app, that holds a user: (model, field name). Hidden relations count too: a
    foreign key declared with related_name="+" (a team captain, a rubber's player) holds a user like any
    other, and Django's related_objects leaves those out."""
    seen = set()
    for relation in User._meta.get_fields(include_hidden=True):
        if not (relation.auto_created and not relation.concrete and relation.is_relation):
            continue
        if relation.many_to_many:
            through = relation.through
            columns = [f.name for f in through._meta.fields if f.is_relation and f.related_model is User]
            found = [(through, name) for name in columns]
        else:
            found = [(relation.related_model, relation.field.name)]
        for model, name in found:
            if model._meta.app_label in SKIPPED or model in RECOMPUTED or (model, name) in seen:
                continue
            seen.add((model, name))
            yield model, name


def _words(model) -> str:
    meta = model._meta
    return CLASH_WORDS.get((meta.app_label, meta.model_name), f"Both have {meta.verbose_name_plural}")


def move(guest_user, claimant) -> None:
    """Point everything of the guest's at the claimant, or raise Clash and change nothing. Call inside
    a transaction."""
    clashes: list[str] = []
    with transaction.atomic():
        for model, field in _references():
            rows = model._base_manager.filter(**{field: guest_user})
            if not rows.exists():
                continue
            try:
                with transaction.atomic():
                    rows.update(**{field: claimant})
            except IntegrityError:
                words = _words(model)
                if words not in clashes:
                    clashes.append(words)
        if clashes:
            raise Clash(clashes)
        had_ratings = (
            RatingEvent.objects.filter(user=guest_user).exists()
            or Rating.objects.filter(user=guest_user).exists()
        )
        Rating.objects.filter(user=guest_user).delete()
        RatingEvent.objects.filter(user=guest_user).delete()
    if had_ratings:
        outbox.enqueue(RERATE, f"{RERATE}:{guest_user.pk}:{claimant.pk}", {})


@outbox.handler(RERATE)
def rerate(_payload: dict) -> None:
    """The guest's results are the claimant's now: write the ledgers again from them."""
    for discipline in Discipline.values:
        ratings.rebuild(discipline)
