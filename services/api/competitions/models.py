import uuid

from django.conf import settings
from django.db import models

from facilities.models import Table, Venue
from organizations.models import Organization

MAX_EVENTS = 30
MAX_TIE_RUBBERS = 9
# The usual club tie: four singles around a doubles, first team to three.
DEFAULT_TIE_RUBBERS = ["singles", "singles", "doubles", "singles", "singles"]
DEFAULT_TIE_WINS = 3


class TournamentQuerySet(models.QuerySet):
    def detailed(self):
        """With host, venue and events (each with its number of accepted entries), for serializing."""
        # Ordered explicitly: an aggregate drops the model's default ordering.
        events = Event.objects.annotate(
            accepted_count=models.Count("entries", filter=models.Q(entries__status="accepted"))
        ).order_by("position", "created_at")
        return self.select_related("organization", "venue").prefetch_related(
            models.Prefetch("events", queryset=events)
        )


class Tournament(models.Model):
    """A competition hosted by one organization at one venue (REQ-007). Its dates are calendar days in
    `timezone`. Drafts exist only for the host's competition staff; from publication on it is visible to
    everyone, which grants nobody the right to run it."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tournaments")
    venue = models.ForeignKey(
        Venue, on_delete=models.PROTECT, null=True, blank=True, related_name="tournaments"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=2000, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    timezone = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    # The organizers let ready matches go to free tables by themselves, in queue order (REQ-014).
    auto_dispatch = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    objects = TournamentQuerySet.as_manager()

    class Meta:
        ordering = ["starts_on", "name", "id"]
        indexes = [models.Index(fields=["status", "starts_on"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="tournament_dates_in_order"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_closed(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.CANCELLED}


class Event(models.Model):
    """One competition within a tournament: who enters (players, pairs or teams) and how it is played
    (REQ-007). `revision` counts configuration changes, so a published configuration can be told apart
    from a later one."""

    class Kind(models.TextChoices):
        SINGLES = "singles"
        DOUBLES = "doubles"
        TEAM = "team"

    class Format(models.TextChoices):
        ROUND_ROBIN = "round_robin"
        KNOCKOUT = "knockout"
        GROUPS_KNOCKOUT = "groups_knockout"

    class Seeding(models.TextChoices):
        RATING = "rating"  # by current rating
        MANUAL = "manual"  # staff put the entries in seed order
        NONE = "none"  # unseeded draw

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    # What "structure" means for REQ-007: fixed once the event has started.
    STRUCTURE_FIELDS = (
        "kind",
        "format",
        "best_of",
        "seeding",
        "group_count",
        "qualifiers_per_group",
        "tie_rubbers",
        "tie_wins_needed",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    format = models.CharField(max_length=16, choices=Format.choices)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)  # entries; null = no limit
    best_of = models.PositiveSmallIntegerField(default=5)
    rest_minutes = models.PositiveSmallIntegerField(default=10)
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)
    # Declared only (REQ-008); payments are recorded in Phase 2.
    entry_fee_minor = models.PositiveIntegerField(default=0)
    entry_fee_currency = models.CharField(max_length=3, default="KES")
    seeding = models.CharField(max_length=10, choices=Seeding.choices, default=Seeding.RATING)
    group_count = models.PositiveSmallIntegerField(null=True, blank=True)  # groups_knockout only
    qualifiers_per_group = models.PositiveSmallIntegerField(null=True, blank=True)
    # Team events only (REQ-011): the individual matches of a tie in playing order, each "singles" or
    # "doubles", and how many of them a team must win to take the tie.
    tie_rubbers = models.JSONField(default=list, blank=True)
    tie_wins_needed = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    position = models.PositiveSmallIntegerField(default=0)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)
    # Set while a corrected result waits for the organizers' decision about a later match that had
    # already started (REQ-015): no match of the event is sent to a table until every one is settled.
    paused_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self):
        return f"{self.name} ({self.tournament_id})"

    @property
    def is_closed(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.CANCELLED}

    @property
    def is_team(self) -> bool:
        return self.kind == self.Kind.TEAM


class LifecycleEntry(models.Model):
    """Audit trail of a tournament's and its events' state changes (REQ-007): who did what, when and
    why. `snapshot` holds the configuration as it stood at that moment. Entries are never edited."""

    class Action(models.TextChoices):
        PUBLISHED = "published"
        UPDATED = "updated"
        STARTED = "started"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        EVENT_STARTED = "event_started"
        EVENT_COMPLETED = "event_completed"
        EVENT_CANCELLED = "event_cancelled"
        EVENT_REMOVED = "event_removed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="lifecycle")
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    event_name = models.CharField(max_length=80, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    reason = models.CharField(max_length=300, blank=True)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.action} {self.tournament_id}"


MIN_TEAM_ROSTER = 2
MAX_TEAM_ROSTER = 10


class Entry(models.Model):
    """One player, pair or team asking to play an event (REQ-008). Status says where the request stands;
    check-in is tracked on its own and says only that the entry has arrived at the venue. Nothing here
    says anything about payment: the fee is declared on the event and receipts arrive in Phase 2."""

    class Status(models.TextChoices):
        PENDING = "pending"  # waiting for staff
        ACCEPTED = "accepted"  # holds one of the event's places
        WAITLISTED = "waitlisted"  # staff will offer a place if one opens
        REJECTED = "rejected"
        WITHDRAWN = "withdrawn"

    # Statuses in which the entry still stands, so its players can't be in another entry of the event.
    LIVE = (Status.PENDING, Status.ACCEPTED, Status.WAITLISTED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="entries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    team_name = models.CharField(max_length=80, blank=True)  # team events only
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Why staff rejected or withdrew it; shown to the entry's players and to staff only.
    reason = models.CharField(max_length=300, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["event", "status"])]

    def __str__(self):
        return f"{self.get_status_display()} entry {self.id} in {self.event_id}"


class EntryPlayer(models.Model):
    """A player in an entry. `live` mirrors the entry's status so the database itself refuses a player
    in two standing entries of one event, whatever races the requests run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="players")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entry_places")
    position = models.PositiveSmallIntegerField(default=0)
    live = models.BooleanField(default=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["entry", "user"], name="entry_player_once"),
            models.UniqueConstraint(
                fields=["event", "user"], condition=models.Q(live=True), name="one_live_entry_per_event"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.entry_id}"


class DrawVersion(models.Model):
    """One generated draw of an event (REQ-009). A preview is the organizers' working copy; publishing
    makes it the event's draw and supersedes the one before. `rng_seed` and `rules_version` make the
    draw reproducible: the same entries, seeds and seed number always give the same draw."""

    class Status(models.TextChoices):
        PREVIEW = "preview"
        PUBLISHED = "published"
        SUPERSEDED = "superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="draws")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREVIEW)
    rules_version = models.CharField(max_length=40)
    rng_seed = models.BigIntegerField()
    # The event's structure when this was drawn; a draw made for another structure is stale.
    format = models.CharField(max_length=16, choices=Event.Format.choices)
    group_count = models.PositiveSmallIntegerField(null=True, blank=True)
    qualifiers_per_group = models.PositiveSmallIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["event", "version"]
        constraints = [
            models.UniqueConstraint(fields=["event", "version"], name="draw_version_once"),
            models.UniqueConstraint(
                fields=["event"], condition=models.Q(status="published"), name="one_published_draw"
            ),
            models.UniqueConstraint(
                fields=["event"], condition=models.Q(status="preview"), name="one_preview_draw"
            ),
        ]

    def __str__(self):
        return f"Draw v{self.version} of {self.event_id} ({self.status})"


class DrawPlace(models.Model):
    """Where one entry sits in a draw: its seed, its group and number in the group, and its line in the
    first round of the knockout."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draw = models.ForeignKey(DrawVersion, on_delete=models.CASCADE, related_name="places")
    entry = models.ForeignKey(Entry, on_delete=models.PROTECT, related_name="draw_places")
    seed = models.PositiveSmallIntegerField(null=True, blank=True)
    group = models.PositiveSmallIntegerField(null=True, blank=True)  # 1-based group number
    group_position = models.PositiveSmallIntegerField(null=True, blank=True)  # number within the group
    bracket_position = models.PositiveSmallIntegerField(null=True, blank=True)  # line in round one

    class Meta:
        ordering = ["group", "group_position", "bracket_position"]
        constraints = [models.UniqueConstraint(fields=["draw", "entry"], name="draw_place_once")]

    def __str__(self):
        return f"{self.entry_id} in draw {self.draw_id}"


class Match(models.Model):
    """A match of a draw. A side is an entry, or still to come: the winner of an earlier match
    (`feeder_*`) or a group's qualifier (`*_from_group`, `*_from_rank`). A bye is a first-round line
    with nobody opposite: the entry goes through, nothing is played and nothing is rated."""

    class Stage(models.TextChoices):
        GROUP = "group"
        KNOCKOUT = "knockout"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        BYE = "bye"
        COMPLETED = "completed"

    class Outcome(models.TextChoices):
        PLAYED = "played"  # finished at the table
        WALKOVER = "walkover"  # never started: the loser didn't play
        RETIRED = "retired"  # started but not finished: the loser couldn't go on

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draw = models.ForeignKey(DrawVersion, on_delete=models.CASCADE, related_name="matches")
    stage = models.CharField(max_length=10, choices=Stage.choices)
    group = models.PositiveSmallIntegerField(null=True, blank=True)
    round = models.PositiveSmallIntegerField()  # 1-based within its stage (and group)
    position = models.PositiveSmallIntegerField()  # 1-based within the round
    entry_a = models.ForeignKey(Entry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    entry_b = models.ForeignKey(Entry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    feeder_a = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    feeder_b = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    a_from_group = models.PositiveSmallIntegerField(null=True, blank=True)
    a_from_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    b_from_group = models.PositiveSmallIntegerField(null=True, blank=True)
    b_from_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    winner = models.ForeignKey(Entry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # How a completed match ended, and the points of each game as [a, b] pairs in playing order.
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    games = models.JSONField(default=list, blank=True)
    # Where and when it is expected to be played; both empty until the organizers schedule it. The time
    # is an estimate, never a promise (REQ-014).
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    # When it was sent to its table; empty while it isn't on one (REQ-014).
    dispatched_at = models.DateTimeField(null=True, blank=True)
    # When both its sides became known: how long it has waited orders the ready queue (REQ-014).
    ready_since = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["stage", "group", "round", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["draw", "stage", "group", "round", "position"],
                name="match_line_once",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=models.Q(entry_a__isnull=True) | ~models.Q(entry_a=models.F("entry_b")),
                name="match_sides_differ",
            ),
        ]

    def __str__(self):
        return f"{self.stage} round {self.round} match {self.position} of draw {self.draw_id}"


class Lineup(models.Model):
    """Who one team sends out for each rubber of a tie (REQ-011). `picks` holds, for every rubber of the
    event's tie template in order, the ids of the one or two players chosen. A team's lineup is its own
    until both are in: then the tie begins and the rubbers are made from them."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="lineups")
    entry = models.ForeignKey(Entry, on_delete=models.PROTECT, related_name="lineups")
    picks = models.JSONField(default=list)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    submitted_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["match", "entry"], name="one_lineup_per_team")]

    def __str__(self):
        return f"Lineup of {self.entry_id} for {self.match_id}"


class Rubber(models.Model):
    """One individual match of a team tie (REQ-011): a singles or doubles with its own score. Rubbers
    are played in order, one at a time; once a team has the wins it needs, those left are not played."""

    class Kind(models.TextChoices):
        SINGLES = "singles"
        DOUBLES = "doubles"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        COMPLETED = "completed"
        NOT_PLAYED = "not_played"  # the tie was decided before its turn came

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="rubbers")
    position = models.PositiveSmallIntegerField()  # 1-based playing order
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    winner = models.ForeignKey(Entry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    outcome = models.CharField(max_length=10, choices=Match.Outcome.choices, blank=True)
    # Points of each game as [a, b] pairs, a being the tie's side a.
    games = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["match", "position"], name="rubber_position_once")]

    def __str__(self):
        return f"Rubber {self.position} of {self.match_id}"


class RubberPlayer(models.Model):
    """A player in a rubber, on the side of the team that picked them."""

    class Side(models.TextChoices):
        A = "a"
        B = "b"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rubber = models.ForeignKey(Rubber, on_delete=models.CASCADE, related_name="players")
    side = models.CharField(max_length=1, choices=Side.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["side", "position"]
        constraints = [models.UniqueConstraint(fields=["rubber", "user"], name="rubber_player_once")]

    def __str__(self):
        return f"{self.user_id} in {self.rubber_id}"


class OfficialResult(models.Model):
    """One version of the official result of a match, or of one rubber of a tie (REQ-015). The first
    is written when the server accepts the result; a correction writes the next and keeps the one it
    replaces. Nothing here is ever edited or deleted: `current` says which version stands."""

    class Source(models.TextChoices):
        UMPIRE = "umpire"  # confirmed on the scoring deck
        STAFF = "staff"  # entered by the organizers (a walkover, a retirement, a paper score sheet)
        CORRECTION = "correction"  # replaces an earlier version, with a reason

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="results")
    rubber = models.ForeignKey(
        Rubber, on_delete=models.CASCADE, null=True, blank=True, related_name="results"
    )
    version = models.PositiveSmallIntegerField(default=1)
    winner = models.ForeignKey(Entry, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=10, choices=Match.Outcome.choices)
    games = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=12, choices=Source.choices)
    reason = models.CharField(max_length=300, blank=True)  # corrections only
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    accepted_at = models.DateTimeField(auto_now_add=True)
    # When the match (or rubber) first got an official result: corrections keep it, so whatever is
    # rebuilt from results keeps their original order (REQ-016).
    first_accepted_at = models.DateTimeField()
    current = models.BooleanField(default=True)
    # Set when the result was struck out without a replacement: the match is to be played again.
    voided_at = models.DateTimeField(null=True, blank=True)
    # When what follows from it (ratings, notifications) was done; empty while that is processing.
    projected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["first_accepted_at", "version", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["match"],
                condition=models.Q(current=True, rubber__isnull=True),
                name="one_current_result_per_match",
            ),
            models.UniqueConstraint(
                fields=["rubber"], condition=models.Q(current=True), name="one_current_result_per_rubber"
            ),
        ]

    def __str__(self):
        return f"Result v{self.version} of {self.rubber_id or self.match_id}"


class Resolution(models.Model):
    """A corrected result changed who should play in a later match that had already started (REQ-015).
    The opponent is never replaced silently: the event is paused and this waits for the organizers to
    decide between keeping the later match as played and putting the right entry in to play it again."""

    class Choice(models.TextChoices):
        KEEP = "keep"  # the later match stands as it was played
        REPLACE = "replace"  # the right entry goes in; what was played there is struck out

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="resolutions")
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="resolutions")
    side = models.CharField(max_length=1)  # "a" or "b": the place in `match` that is in question
    old_entry = models.ForeignKey(Entry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # Who should be there now; empty when the match that decides it has to be played again first.
    new_entry = models.ForeignKey(Entry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    cause = models.ForeignKey(OfficialResult, on_delete=models.PROTECT, related_name="resolutions")
    created_at = models.DateTimeField(auto_now_add=True)
    choice = models.CharField(max_length=10, choices=Choice.choices, blank=True)
    note = models.CharField(max_length=300, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    # What was struck out by `replace`: the score sheet's events and the result, kept for the record.
    struck_out = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Resolution for side {self.side} of {self.match_id}"
