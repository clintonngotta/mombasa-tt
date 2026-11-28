"""Keeping draws (REQ-009): a preview the organizers can make again and again, and its publication.

Callers hold the tournament row lock, like every other change to a tournament.
"""

import hashlib
import secrets

from django.db.models import Exists, OuterRef
from django.utils import timezone

from core.exceptions import ApiException
from organizations.models import Membership, Organization
from profiles.models import PlayerProfile
from ratings.elo import START
from ratings.models import Discipline, Rating
from scoring.models import EnginePhase, Scorecard

from . import draws, formats, official, signals, standings
from .models import DrawPlace, DrawVersion, Entry, EntryPlayer, Event, Match, Rubber, Tournament
from .rules import RULES_VERSION

D = DrawVersion.Status


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def ensure_drawable(tournament: Tournament, event: Event) -> None:
    """A draw is made and published between publication of the tournament and the start of the event."""
    if tournament.status == Tournament.Status.DRAFT:
        raise _conflict("not_published", "Publish the tournament before making a draw.")
    if tournament.is_closed or event.status != Event.Status.SCHEDULED:
        raise _conflict(
            "draw_closed", f"This event is {event.get_status_display().lower()}, so its draw can't change."
        )


def accepted_ids(event: Event) -> set[str]:
    return {str(pk) for pk in event.entries.filter(status=Entry.Status.ACCEPTED).values_list("pk", flat=True)}


def rating_seeds(event: Event) -> list[str]:
    if event.seeding != Event.Seeding.RATING:
        return []
    entries = list(event.entries.filter(status=Entry.Status.ACCEPTED).prefetch_related("players"))
    if len(entries) < 2:
        return []
    discipline = Discipline.DOUBLES if event.kind == Event.Kind.DOUBLES else Discipline.SINGLES
    user_ids = {place.user_id for entry in entries for place in entry.players.all()}
    ratings = dict(
        Rating.objects.filter(discipline=discipline, user_id__in=user_ids, played__gt=0).values_list(
            "user_id", "rating"
        )
    )
    ranked = []
    for entry in entries:
        players = [place.user_id for place in entry.players.all()]
        if any(user_id in ratings for user_id in players):
            rating = sum(ratings.get(user_id, START) for user_id in players) / len(players)
            ranked.append((-rating, entry.created_at, str(entry.id)))
    return [entry_id for _, _, entry_id in sorted(ranked)[: draws.MAX_SEEDS]]


# What the organizers may keep apart in the groups, and the organizations each choice covers: clubs
# are places people train at, teams are players without one (REQ-057).
KEEP_APART = ("clubs", "teams", "regions")
KINDS_KEPT_APART = {
    "clubs": (Organization.Kind.CLUB, Organization.Kind.CLUB_FACILITY),
    "teams": (Organization.Kind.TEAM,),
}


def affiliations(entry_ids, keep=KEEP_APART) -> tuple[dict[str, set[str]], dict[str, str]]:
    """For each entry, as keys, the clubs and teams its players are active members of and the regions
    they live in (their profiles), as far as `keep` asks for them; and a name for each key. A pair or
    team counts once for each club or region any of its players has."""
    entry_ids = list(entry_ids)
    players = list(EntryPlayer.objects.filter(entry_id__in=entry_ids).values_list("entry_id", "user_id"))
    users = {user_id for _, user_id in players}
    of_user: dict = {user_id: set() for user_id in users}
    names: dict[str, str] = {}
    kinds = [kind for choice in keep for kind in KINDS_KEPT_APART.get(choice, ())]
    if kinds:
        memberships = (
            Membership.objects.active()
            .filter(user_id__in=users, organization__kind__in=kinds)
            .values_list("user_id", "organization_id", "organization__name")
        )
        for user_id, organization_id, name in memberships:
            key = f"org:{organization_id}"
            of_user[user_id].add(key)
            names[key] = name
    if "regions" in keep:
        regions = (
            PlayerProfile.objects.filter(user_id__in=users)
            .exclude(region="")
            .values_list("user_id", "country", "region")
        )
        for user_id, country, region in regions:
            key = f"region:{country}:{region.strip().lower()}"
            of_user[user_id].add(key)
            names.setdefault(key, region.strip())
    found: dict[str, set[str]] = {str(entry_id): set() for entry_id in entry_ids}
    for entry_id, user_id in players:
        found[str(entry_id)] |= of_user[user_id]
    return found, names


def limit_breaches(draw: DrawVersion, places) -> list[dict]:
    """Groups of the draw holding more entries of one club, team or region than the limit allows, as
    DrawSerializer shows them. A draw with one group (or none) has nothing to keep apart."""
    groups: dict[int, list[str]] = {}
    for place in places:
        if place.group:
            groups.setdefault(place.group, []).append(str(place.entry_id))
    if len(groups) < 2 or not draw.keep_apart or draw.event.kind == Event.Kind.JUMBLES:
        return []
    numbers = sorted(groups)
    entries = [entry for members in groups.values() for entry in members]
    found, names = affiliations(entries, draw.keep_apart)
    return [
        {"group": numbers[index - 1], "name": names[key], "count": count, "limit": limit}
        for index, key, count, limit in draws.over_limit(
            [groups[number] for number in numbers], found, draw.same_group_limit
        )
    ]


def is_stale(draw: DrawVersion, places=None) -> bool:
    """The accepted entries or the event's format are no longer the ones this draw was made for."""
    if draw.status == D.SUPERSEDED:
        return False
    event = draw.event
    drawn_for = (draw.format, draw.group_count, draw.qualifiers_per_group)
    if drawn_for != (event.format, event.group_count, event.qualifiers_per_group):
        return True
    places = draw.places.all() if places is None else places
    return {str(place.entry_id) for place in places} != accepted_ids(event)


def make_preview(
    event: Event,
    actor,
    seeds: list[str],
    rng_seed: int | None = None,
    keep_apart=KEEP_APART,
    limit: int = draws.SAME_GROUP_LIMIT,
) -> DrawVersion:
    """Draw the accepted entries and keep the result as the event's preview, replacing the last one.
    In a groups stage, at most `limit` entries of one club, team or region named in `keep_apart` share a
    group, unless one has too many entries for that."""
    if seeds and event.seeding == Event.Seeding.NONE:
        raise _conflict("unseeded_event", "This event is unseeded. Change its seeding to seed entries.")
    if rng_seed is None:
        rng_seed = secrets.randbelow(2**31)
    if event.kind == Event.Kind.JUMBLES:
        from . import jumbles

        for old in event.draws.filter(status=D.PREVIEW):
            jumbles.drop(old)
        last = event.draws.order_by("-version").values_list("version", flat=True).first() or 0
        return jumbles.make_draw(event, actor, rng_seed, last + 1, RULES_VERSION)
    entries = list(accepted_ids(event))
    keep_apart = [choice for choice in KEEP_APART if choice in keep_apart]
    grouped = event.format == Event.Format.GROUPS_KNOCKOUT
    spread = affiliations(entries, keep_apart)[0] if grouped and keep_apart else None
    try:
        plan = draws.build(
            event.format,
            entries,
            seeds,
            rng_seed,
            group_count=event.group_count,
            qualifiers_per_group=event.qualifiers_per_group,
            affiliations=spread,
            limit=limit,
        )
    except draws.DrawError as error:
        raise _conflict("draw_not_possible", str(error)) from error

    event.draws.filter(status=D.PREVIEW).delete()
    last = event.draws.order_by("-version").values_list("version", flat=True).first() or 0
    draw = DrawVersion.objects.create(
        event=event,
        version=last + 1,
        rules_version=RULES_VERSION,
        rng_seed=rng_seed,
        format=event.format,
        group_count=event.group_count,
        qualifiers_per_group=event.qualifiers_per_group,
        keep_apart=keep_apart,
        same_group_limit=limit,
        created_by=actor,
    )
    _save_plan(draw, plan)
    return draw


def _save_plan(draw: DrawVersion, plan: draws.Plan) -> None:
    where: dict[str, dict] = {}
    for number, members in enumerate(plan.groups, start=1):
        for position, entry in enumerate(members, start=1):
            where[entry] = {"group": number, "group_position": position}
    for line, entry in enumerate(plan.lines, start=1):
        if entry:
            where[entry] = {"bracket_position": line}
    DrawPlace.objects.bulk_create(
        DrawPlace(draw=draw, entry_id=entry, seed=plan.seeds.get(entry), **place)
        for entry, place in where.items()
    )

    _save_matches(draw, plan.matches)


def _save_matches(draw: DrawVersion, planned_matches: list[draws.PlannedMatch]) -> None:
    knockout: dict[tuple[int, int], Match] = {}
    for planned in planned_matches:  # rounds come in order, so a feeder is always saved before its match
        a, b = planned.a, planned.b
        match = Match(
            draw=draw,
            stage=planned.stage,
            group=planned.group,
            round=planned.round,
            position=planned.position,
            entry_a_id=a.entry,
            entry_b_id=b.entry if b else None,
            feeder_a=knockout.get(a.feeder) if a.feeder else None,
            feeder_b=knockout.get(b.feeder) if b and b.feeder else None,
            status=Match.Status.SCHEDULED if b else Match.Status.BYE,
            winner_id=a.entry if b is None else None,
        )
        if a.qualifier:
            match.a_from_group, match.a_from_rank = a.qualifier
        if b and b.qualifier:
            match.b_from_group, match.b_from_rank = b.qualifier
        match.save()
        if planned.stage == Match.Stage.KNOCKOUT:
            knockout[planned.round, planned.position] = match


def discard_preview(event: Event) -> None:
    """Throw the preview away so the organizers can start again. The published draw, if there is one,
    stays as it is; with no preview there is nothing to do."""
    for preview in event.draws.filter(status=D.PREVIEW):
        if event.kind == Event.Kind.JUMBLES:
            from . import jumbles

            jumbles.drop(preview)
        else:
            preview.delete()


def publish(event: Event, actor) -> DrawVersion:
    """Make the preview the event's draw. The one published before it is kept as superseded."""
    preview = event.draws.filter(status=D.PREVIEW).first()
    if preview is None:
        raise _conflict("no_preview", "Make a draw to preview before publishing one.")
    if is_stale(preview):
        raise _conflict(
            "draw_stale", "The accepted entries or the format changed since this draw was made. Draw again."
        )
    over = limit_breaches(preview, list(preview.places.all()))
    if over:
        first = over[0]
        raise _conflict(
            "draw_over_limit",
            f"{group_name(first['group'])} has {first['count']} entries from {first['name']}; it may have "
            f"{first['limit']} at most. Move entries between groups before publishing.",
        )
    event.draws.filter(status=D.PUBLISHED).update(status=D.SUPERSEDED)
    preview.status = D.PUBLISHED
    preview.published_by = actor
    preview.published_at = timezone.now()
    preview.save(update_fields=["status", "published_by", "published_at"])
    mark_ready(preview)
    return preview


def move(
    event: Event, actor, entry_id: str, *, group: int | None = None, swap_with: str | None = None
) -> None:
    """Move an entry of the preview by hand: into another group (`group`), or into the place of another
    entry (`swap_with`), in a group or on a knockout line. The matches the move touches are made again;
    nothing has been played in a preview. Group numbers follow seeds, then the order drawn, the moved
    entry last among the unseeded."""
    preview = event.draws.filter(status=D.PREVIEW).first()
    if preview is None:
        raise _conflict("no_preview", "Make a draw to preview before moving entries in it.")
    if event.kind == Event.Kind.JUMBLES:
        raise _conflict("not_movable", "A Jumbles draw makes new pairs each round; draw it again instead.")
    places = {str(place.entry_id): place for place in preview.places.all()}
    place = places.get(str(entry_id))
    other = places.get(str(swap_with)) if swap_with else None
    if place is None or (swap_with and other is None):
        raise ApiException("not_in_draw", "Choose entries of this draw.", 400)
    if other is place:
        raise ApiException("invalid_move", "Choose two different entries to swap.", 400)

    if preview.format == Event.Format.KNOCKOUT:
        if other is None:
            raise ApiException("invalid_move", "In a knockout, swap two entries' places.", 400)
        place.bracket_position, other.bracket_position = other.bracket_position, place.bracket_position
        DrawPlace.objects.bulk_update([place, other], ["bracket_position"])
        lines: list[str | None] = [None] * draws.bracket_size(len(places))
        for found in places.values():
            lines[found.bracket_position - 1] = str(found.entry_id)
        preview.matches.all().delete()
        _save_matches(
            preview, draws.knockout_matches([draws.Side(entry) if entry else None for entry in lines])
        )
    else:
        if preview.format != Event.Format.GROUPS_KNOCKOUT:
            raise _conflict(
                "not_movable", "A round robin is one group: there is nowhere to move an entry to."
            )
        groups = preview.group_count or 0
        before = place.group
        if other is not None:
            if other.group == place.group:
                raise ApiException("invalid_move", "Those two entries are already in the same group.", 400)
            place.group, other.group = other.group, place.group
            place.group_position, other.group_position = other.group_position, place.group_position
        else:
            if group is None or not 1 <= group <= groups:
                raise ApiException("invalid_move", f"Choose a group from 1 to {groups}.", 400)
            if group == place.group:
                raise ApiException("invalid_move", "That entry is already in this group.", 400)
            left = sum(1 for found in places.values() if found.group == place.group) - 1
            if left < (preview.qualifiers_per_group or 1) + 1:
                raise _conflict(
                    "group_too_small",
                    f"{group_name(place.group)} would have {left} entries, too few to send "
                    f"{preview.qualifiers_per_group} through. Swap entries instead.",
                )
            place.group, place.group_position = group, 10_000  # last of the group until renumbered
        _renumber(preview, places.values(), sorted({before, place.group}))
    preview.moved_at = timezone.now()
    preview.moved_by = actor
    preview.save(update_fields=["moved_at", "moved_by"])


# Copied when the published draw is taken up again: everything a match of a draw not yet started holds.
COPIED_MATCH_FIELDS = (
    "stage", "group", "round", "position", "entry_a_id", "entry_b_id", "a_from_group", "a_from_rank",
    "b_from_group", "b_from_rank", "status", "winner_id", "outcome", "games", "scheduled_at",
    "planned_table_id", "draft_table_id", "draft_at",
)  # fmt: skip


def reopen(event: Event, actor) -> DrawVersion:
    """Take the published draw up again as the preview, exactly as it is: the same groups, numbers,
    seeds, knockout and planned times, and the same rules. Late entries are then added to a group and
    withdrawn ones taken out, each touching only its group, and the result is published as a new
    version. Replaces a preview being worked on."""
    published = event.draws.filter(status=D.PUBLISHED).first()
    if published is None:
        raise _conflict("no_published_draw", "There is no published draw to start from. Make the draw.")
    if event.kind == Event.Kind.JUMBLES:
        raise _conflict("not_movable", "A Jumbles draw makes new pairs each round; draw it again instead.")
    discard_preview(event)
    last = event.draws.order_by("-version").values_list("version", flat=True).first() or 0
    copy = DrawVersion.objects.create(
        event=event,
        version=last + 1,
        rules_version=published.rules_version,
        rng_seed=published.rng_seed,
        format=published.format,
        group_count=published.group_count,
        qualifiers_per_group=published.qualifiers_per_group,
        keep_apart=published.keep_apart,
        same_group_limit=published.same_group_limit,
        created_by=actor,
        moved_at=timezone.now(),
        moved_by=actor,
    )
    DrawPlace.objects.bulk_create(
        DrawPlace(
            draw=copy,
            entry_id=place.entry_id,
            seed=place.seed,
            group=place.group,
            group_position=place.group_position,
            bracket_position=place.bracket_position,
        )
        for place in published.places.all()
    )
    copied: dict = {}
    # Feeders come before the matches they feed: by stage, then round.
    for match in published.matches.order_by("stage", "round", "position"):
        made = Match(draw=copy, **{name: getattr(match, name) for name in COPIED_MATCH_FIELDS})
        made.feeder_a_id = copied.get(match.feeder_a_id)
        made.feeder_b_id = copied.get(match.feeder_b_id)
        made.save()
        copied[match.id] = made.id
    return copy


def missing_entries(draw: DrawVersion, places) -> list[Entry]:
    """Accepted entries of the event the draw doesn't hold: entered or accepted since it was made."""
    placed = {place.entry_id for place in places}
    return list(
        draw.event.entries.filter(status=Entry.Status.ACCEPTED)
        .exclude(pk__in=placed)
        .prefetch_related("players__user")
        .order_by("created_at")
    )


def suggested_group(draw: DrawVersion, places, entry_id) -> int | None:
    """Where a late entry fits best: the smallest group it can join without breaking the draw's rules,
    the first such; or the smallest group when none can. None for a draw without groups."""
    groups: dict[int, list[str]] = {}
    for place in places:
        if place.group:
            groups.setdefault(place.group, []).append(str(place.entry_id))
    if not groups:
        return None
    numbers = sorted(groups, key=lambda number: (len(groups[number]), number))
    if draw.keep_apart and len(groups) > 1:
        entries = [entry for members in groups.values() for entry in members] + [str(entry_id)]
        found = affiliations(entries, draw.keep_apart)[0]
        for number in numbers:
            trial = [groups[n] + ([str(entry_id)] if n == number else []) for n in sorted(groups)]
            if not draws.over_limit(trial, found, draw.same_group_limit):
                return number
    return numbers[0]


def add_entry(event: Event, actor, entry_id: str, group: int) -> None:
    """Put an accepted entry the preview doesn't hold yet into a group, last among its unseeded, and
    make that group's matches again. A knockout's bracket and byes depend on how many entered, so a
    late entry there means drawing again."""
    preview = event.draws.filter(status=D.PREVIEW).first()
    if preview is None:
        raise _conflict("no_preview", "Start from the published draw, or make a draw, first.")
    if event.kind == Event.Kind.JUMBLES:
        raise _conflict("not_movable", "A Jumbles draw makes new pairs each round; draw it again instead.")
    if preview.format == Event.Format.KNOCKOUT:
        raise _conflict("not_addable", "A knockout's bracket depends on how many entered: draw it again.")
    entry = event.entries.filter(pk=entry_id, status=Entry.Status.ACCEPTED).first()
    if entry is None:
        raise ApiException("not_in_draw", "Choose an accepted entry of this event.", 400)
    places = list(preview.places.all())
    if any(place.entry_id == entry.id for place in places):
        raise ApiException("invalid_move", "That entry is already in the draw.", 400)
    groups = (preview.group_count or 1) if preview.format == Event.Format.GROUPS_KNOCKOUT else 1
    if not 1 <= group <= groups:
        raise ApiException("invalid_move", f"Choose a group from 1 to {groups}.", 400)
    place = DrawPlace.objects.create(draw=preview, entry=entry, group=group, group_position=10_000)
    _renumber(preview, [*places, place], [group])
    preview.moved_at = timezone.now()
    preview.moved_by = actor
    preview.save(update_fields=["moved_at", "moved_by"])


def remove_entry(event: Event, actor, entry_id: str) -> None:
    """Take an entry that is no longer accepted (withdrawn, rejected) out of its group in the preview and
    make that group's matches again. An accepted entry is moved, never taken out."""
    preview = event.draws.filter(status=D.PREVIEW).first()
    if preview is None:
        raise _conflict("no_preview", "Start from the published draw, or make a draw, first.")
    places = list(preview.places.select_related("entry"))
    place = next((found for found in places if str(found.entry_id) == str(entry_id)), None)
    if place is None:
        raise ApiException("not_in_draw", "Choose entries of this draw.", 400)
    if place.entry.status == Entry.Status.ACCEPTED:
        raise ApiException("invalid_move", "Only an entry that is no longer accepted is taken out.", 400)
    if not place.group:
        raise _conflict("not_addable", "A knockout's bracket depends on how many entered: draw it again.")
    left = sum(1 for found in places if found.group == place.group) - 1
    needed = (preview.qualifiers_per_group or 1) + 1 if preview.format == Event.Format.GROUPS_KNOCKOUT else 2
    if left < needed:
        raise _conflict(
            "group_too_small",
            f"{group_name(place.group)} would have {left} entries. Move an entry into it first.",
        )
    place.delete()
    _renumber(preview, [found for found in places if found is not place], [place.group])
    preview.moved_at = timezone.now()
    preview.moved_by = actor
    preview.save(update_fields=["moved_at", "moved_by"])


def _renumber(draw: DrawVersion, places, touched: list[int]) -> None:
    """Number the members of the touched groups again (seeds first, then in the order they sit) and make
    those groups' matches again. Knockout places wait for (group, rank), so they stay as they are."""
    changed: list[DrawPlace] = []
    for number in touched:
        members = sorted(
            (found for found in places if found.group == number),
            key=lambda found: (found.seed is None, found.seed or 0, found.group_position or 0),
        )
        for position, found in enumerate(members, start=1):
            found.group_position = position
            changed.append(found)
    DrawPlace.objects.bulk_update(changed, ["group", "group_position"])
    draw.matches.filter(stage=Match.Stage.GROUP, group__in=touched).delete()
    planned = []
    for number in touched:
        members = [str(found.entry_id) for found in changed if found.group == number]  # already in order
        planned += draws.group_matches(number, members, draw.qualifiers_per_group or 1)
    _save_matches(draw, planned)


def mark_ready(draw: DrawVersion) -> None:
    """Note the moment a match of the draw has both its sides: its waiting starts here."""
    draw.matches.filter(
        status=Match.Status.SCHEDULED,
        entry_a__isnull=False,
        entry_b__isnull=False,
        ready_since__isnull=True,
    ).update(ready_since=timezone.now())


def record_result(
    match: Match,
    winner: Entry,
    *,
    outcome: str = Match.Outcome.PLAYED,
    games=(),
    actor=None,
    source: str = official.Source.UMPIRE,
    reason: str = "",
) -> None:
    """The match is decided: the winner moves into the match it feeds, and a finished group sends its
    qualifiers into the knockout. `games` are [a, b] points in playing order. Who may decide a match,
    score validation and corrections arrive with official results; this is the progression."""
    if match.draw.status != D.PUBLISHED:
        raise _conflict("draw_not_published", "Only matches of the published draw are played.")
    if match.status != Match.Status.SCHEDULED:
        raise _conflict("match_decided", "This match is already decided.")
    if match.entry_a_id is None or match.entry_b_id is None:
        raise _conflict("match_not_ready", "Both sides of this match aren't known yet.")
    if winner.id not in (match.entry_a_id, match.entry_b_id):
        raise _conflict("not_in_match", "The winner is one of the two sides of the match.")
    official.ensure_not_held(match)
    event = match.draw.event
    if event.is_team:
        # A tie has no games of its own. It is played to its end through its rubbers; or it is awarded:
        # before any rubber is decided (walkover), part-way when a team can't go on (retired), or at
        # any point before it is won when the referee disqualifies a team.
        most = max(tie_score(match))
        needed = event.tie_wins_needed or 0
        any_decided = match.rubbers.exclude(status=Rubber.Status.SCHEDULED).exists()
        fits = {
            Match.Outcome.PLAYED: tie_score(match)[winner.id != match.entry_a_id] >= needed > 0,
            Match.Outcome.WALKOVER: not any_decided,
            Match.Outcome.RETIRED: any_decided and most < needed,
            Match.Outcome.DISQUALIFIED: most < needed,
        }
        if games or not fits.get(outcome, False):
            raise ApiException(
                "invalid_result",
                "A tie is decided by its rubbers, or awarded when a team doesn't play or can't go on.",
                400,
            )
        # Whatever wasn't needed is not played: never scored and never rated.
        match.rubbers.filter(status=Rubber.Status.SCHEDULED).update(status=Rubber.Status.NOT_PLAYED)
    else:
        check_games(formats.best_of_for(match, event), games, outcome, a_won=winner.id == match.entry_a_id)
    match.winner = winner
    match.status = Match.Status.COMPLETED
    match.outcome = outcome
    match.games = [list(game) for game in games]
    match.save(update_fields=["winner", "status", "outcome", "games"])
    # The official record and the work that follows from it, written with the result itself.
    official.accept(match, None, winner, outcome, match.games, actor=actor, source=source, reason=reason)
    _send_on(match)
    if match.stage == Match.Stage.GROUP:
        place_qualifiers(match.draw, match.group)
    mark_ready(match.draw)
    # Whatever the match held (its table, its players) is released in this same transaction.
    signals.match_decided.send(sender=Match, match=match)


def check_games(best_of: int, games, outcome: str, *, a_won: bool) -> None:
    """Refuse games (as [a, b] points) that don't fit how an individual match is said to have ended: a
    played match has exactly the games its winner needed, a walkover none, a retirement too few, a
    disqualification whatever was played before it (none at all if it came before play)."""
    needed = best_of // 2 + 1
    counted = list(games)
    # A retirement or disqualification may stop a game part-way; that game is neither won nor lost.
    if outcome in (Match.Outcome.RETIRED, Match.Outcome.DISQUALIFIED) and counted:
        a, b = counted[-1]
        if not (max(a, b) >= 11 and abs(a - b) >= 2):
            counted.pop()
    won = sum(1 for a, b in counted if (a > b) == a_won and a != b)
    lost = len(counted) - won
    plausible = {
        Match.Outcome.PLAYED: won == needed and lost < needed,
        Match.Outcome.WALKOVER: not games,
        Match.Outcome.RETIRED: won < needed and lost < needed,
        Match.Outcome.DISQUALIFIED: won < needed and lost < needed,
    }
    if not plausible.get(outcome, False):
        raise ApiException("invalid_result", "The games don't fit how this match is said to have ended.", 400)


def _send_on(match: Match) -> None:
    from . import corrections, substitutes  # both build on this module

    for side in ("a", "b"):
        for later in Match.objects.filter(**{f"feeder_{side}": match}).select_related("draw__event"):
            # A match played again after a correction never overwrites a later match that is in
            # question or that the organizers decided to keep as played.
            # A winner who was replaced since (a correction of an old match) is followed by their place.
            winner = substitutes.current(match.winner)
            if corrections.winner_known(later, side, winner):
                continue
            setattr(later, f"entry_{side}", winner)
            later.save(update_fields=[f"entry_{side}"])


def group_table(draw: DrawVersion, group: int) -> tuple[list[standings.Row], bool]:
    """The group in ranking order (3.7.5) and whether every match in it is decided. Until then members
    nobody can separate stay level; afterwards what is left is drawn by lot. The lot's number comes
    from the draw and every score in the group, so it is the same each time the table is looked at but
    nobody can know it, or choose it, before the matches are played."""
    if draw.event.kind == Event.Kind.JUMBLES:
        from . import jumbles

        return jumbles.table(draw)
    members = [
        str(pk)
        for pk in draw.places.filter(group=group)
        .order_by("group_position")
        .values_list("entry_id", flat=True)
    ]
    from . import ties  # ties builds on this module, so it is imported here and not at the top

    team = draw.event.is_team
    matches = list(draw.matches.filter(stage=Match.Stage.GROUP, group=group).prefetch_related("rubbers"))
    from . import substitutes  # substitutes builds on the models this module uses

    # A player swapped in carries on the place: the results of the entry they replaced count as theirs.
    carried = substitutes.carried(draw.event) if not team else {}
    results = []
    for match in matches:
        match.draw = draw  # the draw and its event are already loaded
        if match.status != Match.Status.COMPLETED:
            continue
        if team:
            results.append(ties.result_of(match))
            continue
        a_won = match.winner_id == match.entry_a_id
        loser = match.entry_b_id if a_won else match.entry_a_id
        games = tuple((a, b) if a_won else (b, a) for a, b in match.games)
        results.append(
            standings.Result(
                carried.get(str(match.winner_id), str(match.winner_id)),
                carried.get(str(loser), str(loser)),
                match.outcome or Match.Outcome.PLAYED,
                games,
                best_of=formats.best_of_at(draw.event, formats.GROUP),
            )
        )
    complete = len(results) == len(matches)
    scores = sorted(
        (
            str(match.id),
            str(match.winner_id),
            match.outcome,
            match.games,
            [rubber.games for rubber in match.rubbers.all()] if team else [],
        )
        for match in matches
    )
    lot = hashlib.sha256(repr((str(draw.id), draw.rng_seed, group, scores)).encode()).digest()
    rows = standings.rank(
        members, results, final=complete, lot_seed=int.from_bytes(lot[:8], "big"), team=team
    )
    return rows, complete


def place_qualifiers(draw: DrawVersion, group: int) -> None:
    """Once a group is finished, write its qualifiers into the knockout places that wait for them."""
    rows, complete = group_table(draw, group)
    if not complete:
        return
    knockout = draw.matches.filter(stage=Match.Stage.KNOCKOUT)
    for row in rows:
        knockout.filter(a_from_group=group, a_from_rank=row.rank).update(entry_a=row.member)
        knockout.filter(b_from_group=group, b_from_rank=row.rank).update(entry_b=row.member)
    # A qualifier whose first knockout match is a bye is through it now that we know who it is.
    for bye in knockout.filter(status=Match.Status.BYE, winner__isnull=True, entry_a__isnull=False):
        bye.winner_id = bye.entry_a_id
        bye.save(update_fields=["winner"])
        _send_on(bye)


def placements(draw: DrawVersion) -> list[dict]:
    """What the knockout has decided so far: the winner and runner-up once the final is played, and who
    went out in each round that is finished. Nothing is ranked that hasn't been decided."""
    if draw.event.kind == Event.Kind.JUMBLES:
        from . import jumbles

        return jumbles.placements(draw)
    by_round: dict[int, list[Match]] = {}
    for match in draw.matches.filter(stage=Match.Stage.KNOCKOUT):
        by_round.setdefault(match.round, []).append(match)
    found = []
    for number in sorted(by_round, reverse=True):
        played = [match for match in by_round[number] if match.status != Match.Status.BYE]
        if not played or any(match.status != Match.Status.COMPLETED for match in played):
            continue
        losers = [m.entry_b_id if m.winner_id == m.entry_a_id else m.entry_a_id for m in played]
        name = round_name(number, len(by_round))
        if name == "Final":
            found.append({"label": "Winner", "entry_ids": [played[0].winner_id]})
            found.append({"label": "Runner-up", "entry_ids": losers})
        else:
            found.append(
                {"label": f"Lost in the {name.lower()}{'s' if len(played) > 1 else ''}", "entry_ids": losers}
            )
    return found


def group_name(number: int) -> str:
    return f"Group {chr(64 + number)}" if number <= 26 else f"Group {number}"


def round_name(round_number: int, rounds: int) -> str:
    left = rounds - round_number
    return {0: "Final", 1: "Semi-final", 2: "Quarter-final"}.get(left) or f"Round of {2 ** (left + 1)}"


def ordinal(rank: int) -> str:
    return {1: "winner", 2: "runner-up"}.get(rank) or f"number {rank}"


def describe(draw: DrawVersion, staff: bool = False) -> dict:
    """The draw as DrawSerializer shows it."""
    places = list(draw.places.select_related("entry").prefetch_related("entry__players__user"))
    entries = _entries_of(draw, places)
    seeds = {place.entry_id: place.seed for place in places}
    matches = _matches_of(draw)
    shown = _match_describer(
        matches,
        entries,
        seeds,
        draw.event.status == Event.Status.IN_PROGRESS,
        _times_shown(draw, staff),
        draw.event,
    )
    numbers = sorted({place.group for place in places if place.group})
    # Who each entry is kept apart from, for the organizers moving entries of their preview.
    working = staff and draw.status == D.PREVIEW
    found, names = affiliations([p.entry_id for p in places], draw.keep_apart) if working else ({}, {})
    for place in places:
        place.affiliations = sorted(names[key] for key in found.get(str(place.entry_id), ()))
        # Withdrawn or rejected since the draw was made: the organizers take it out of its group.
        place.withdrawn = working and place.entry.status != Entry.Status.ACCEPTED
    return {
        "id": draw.id,
        "version": draw.version,
        "status": draw.status,
        "rules_version": draw.rules_version,
        "rng_seed": draw.rng_seed,
        "stale": is_stale(draw, places),
        "created_at": draw.created_at,
        "published_at": draw.published_at,
        "moved_at": draw.moved_at,
        "keep_apart": draw.keep_apart,
        "same_group_limit": draw.same_group_limit,
        "over_limit": limit_breaches(draw, places) if working else [],
        "not_in_draw": [
            {"entry": entry, "suggested_group": suggested_group(draw, places, entry.id)}
            for entry in missing_entries(draw, places)
        ]
        if working
        else [],
        "groups": [{"number": number, "name": group_name(number)} for number in numbers],
        "places": places,
        "matches": [shown(match) for match in matches],
    }


def _entries_of(draw: DrawVersion, places) -> dict:
    """The entries the draw's matches are between: its places, and in Jumbles the pairs it made."""
    entries = {place.entry_id: place.entry for place in places}
    entries.update({pairing.id: pairing for pairing in draw.pairings.prefetch_related("players__user")})
    return entries


def _matches_of(draw: DrawVersion) -> list[Match]:
    """Load matches, tables, rubbers and the scoring activity needed for the draw."""
    active_sheets = Scorecard.objects.filter(state__status=EnginePhase.IN_PROGRESS, confirmed_at__isnull=True)
    return list(
        draw.matches.select_related("table", "planned_table")
        .prefetch_related("rubbers")
        .annotate(
            scoring_live=Exists(active_sheets.filter(match_id=OuterRef("pk")))
            | Exists(
                active_sheets.filter(rubber__match_id=OuterRef("pk"), rubber__status=Rubber.Status.SCHEDULED)
            )
        )
    )


def _times_shown(draw: DrawVersion, staff: bool) -> bool:
    """Planned starts and tables are public once the order of play is out (REQ-053); the host's
    competition staff see them from the moment they publish."""
    from . import order_of_play

    return staff or order_of_play.times_shown(draw.event.tournament)


def _match_describer(
    matches: list[Match], entries: dict, seeds: dict, event_in_progress: bool, times: bool, event: Event
):
    """A function turning one of `matches` (all those of a draw) into what MatchSerializer shows.
    Without `times`, planned starts and tables are left out: the order of play isn't out yet."""
    by_id = {match.id: match for match in matches}
    rounds = max((match.round for match in matches if match.stage == Match.Stage.KNOCKOUT), default=0)

    def side(entry_id, feeder_id, from_group, from_rank) -> dict:
        if entry_id:
            return {"entry": entries[entry_id], "seed": seeds.get(entry_id), "awaiting": ""}
        feeder = by_id.get(feeder_id)
        if feeder and feeder.status == Match.Status.BYE:
            # Through a bye: it is simply that qualifier's place.
            from_group, from_rank, feeder = feeder.a_from_group, feeder.a_from_rank, None
        if feeder:
            awaiting = f"Winner of {round_name(feeder.round, rounds).lower()} {feeder.position}"
        else:
            awaiting = f"{group_name(from_group)} {ordinal(from_rank)}"
        return {"entry": None, "seed": None, "awaiting": awaiting}

    def shown(match: Match) -> dict:
        knockout = match.stage == Match.Stage.KNOCKOUT
        return {
            "id": match.id,
            "stage": match.stage,
            "group": match.group,
            "round": match.round,
            "round_name": round_name(match.round, rounds) if knockout else f"Round {match.round}",
            "position": match.position,
            "a": side(match.entry_a_id, match.feeder_a_id, match.a_from_group, match.a_from_rank),
            "b": None
            if match.status == Match.Status.BYE
            else side(match.entry_b_id, match.feeder_b_id, match.b_from_group, match.b_from_rank),
            "status": match.status,
            "is_live": event_in_progress and match.status == Match.Status.SCHEDULED and match.scoring_live,
            "winner_id": match.winner_id,
            "outcome": match.outcome,
            "games": match.games,
            "tie_score": list(tie_score(match)) if match.rubbers.all() else None,
            "table": _table_label(match) if times else (match.table.label if match.table else ""),
            "dispatched_at": match.dispatched_at,
            "scheduled_at": match.scheduled_at if times else None,
            "best_of": formats.best_of_at(
                event, formats.knockout_stage(match.round, rounds) if knockout else formats.GROUP
            ),
        }

    return shown


def _table_label(match: Match) -> str:
    """Where it is, or else where the schedule plans it."""
    table = match.table or match.planned_table
    return table.label if table else ""


def tie_score(match: Match) -> tuple[int, int]:
    """Rubbers won by side a and side b of a tie."""
    won = [rubber.winner_id for rubber in match.rubbers.all() if rubber.winner_id]
    return won.count(match.entry_a_id), won.count(match.entry_b_id)


def describe_match(draw: DrawVersion, match_id, staff: bool = False) -> dict | None:
    """One match of the draw as MatchDetailSerializer shows it, or None when it isn't in this draw."""
    places = list(draw.places.select_related("entry").prefetch_related("entry__players__user"))
    matches = _matches_of(draw)
    match = next((found for found in matches if found.id == match_id), None)
    if match is None:
        return None
    shown = _match_describer(
        matches,
        _entries_of(draw, places),
        {place.entry_id: place.seed for place in places},
        draw.event.status == Event.Status.IN_PROGRESS,
        _times_shown(draw, staff),
        draw.event,
    )
    # A winner of this match plays on in the match it feeds; the final feeds nothing.
    onward = next((m for m in matches if match.id in (m.feeder_a_id, m.feeder_b_id)), None)
    multiple = len({place.group for place in places if place.group}) > 1
    return {
        **shown(match),
        "group_name": group_name(match.group) if match.group and multiple else "",
        "winner_plays_in": shown(onward)["round_name"] if onward else "",
        "draw_version": draw.version,
        "match": match,
    }


def standings_of(draw: DrawVersion) -> dict:
    """The published draw's standings as StandingsSerializer shows them."""
    places = list(draw.places.select_related("entry").prefetch_related("entry__players__user"))
    entries = {str(place.entry_id): place.entry for place in places}
    knockout_follows = draw.format == Event.Format.GROUPS_KNOCKOUT
    qualifiers = draw.qualifiers_per_group if knockout_follows else 0
    groups = []
    for number in sorted({place.group for place in places if place.group}):
        rows, complete = group_table(draw, number)
        groups.append(
            {
                "number": number,
                "name": group_name(number),
                "complete": complete,
                "qualifiers": qualifiers,
                "rows": [
                    {
                        **{name: getattr(row, name) for name in STANDING_FIELDS},
                        "entry": entries[row.member],
                        "qualified": (row.rank <= qualifiers) if complete and knockout_follows else None,
                        "tie_break": [
                            {"among": step.among, "measure": step.measure, "value": step.value}
                            for step in row.steps
                        ],
                    }
                    for row in rows
                ],
            }
        )
    return {
        "rules_version": draw.rules_version,
        "groups": groups,
        "placements": [
            {"label": found["label"], "entries": [entries[str(pk)] for pk in found["entry_ids"]]}
            for found in placements(draw)
        ],
    }


STANDING_FIELDS = (
    "rank",
    "played",
    "won",
    "lost",
    "match_points",
    "games_won",
    "games_lost",
    "points_won",
    "points_lost",
    "level",
)
