import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from attachments.models import Attachment
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
        return self.select_related(
            "organization", "organization__coach_organizer__user", "venue"
        ).prefetch_related(models.Prefetch("events", queryset=events), "documents")


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

    class Scope(models.TextChoices):
        LOCAL = "local", "Local"
        REGIONAL = "regional", "Regional"
        NATIONAL = "national", "National"
        INTERNATIONAL = "international", "International"

    class PresentedAs(models.TextChoices):
        """How a coach's tournament names its organizer: the coach, or the firm they work through."""

        COACH = "coach", "The coach"
        FIRM = "firm", "The coach's firm"

    class Approval(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Not requested"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tournaments")
    venue = models.ForeignKey(
        Venue, on_delete=models.PROTECT, null=True, blank=True, related_name="tournaments"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=2000, blank=True)
    # Only for a tournament hosted from a coach's organizing desk; blank for every other host.
    presented_as = models.CharField(max_length=5, choices=PresentedAs.choices, blank=True)
    cover = models.ForeignKey(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    starts_on = models.DateField()
    ends_on = models.DateField()
    timezone = models.CharField(max_length=64)
    scope = models.CharField(max_length=13, choices=Scope.choices, default=Scope.LOCAL)
    approval_status = models.CharField(
        max_length=13, choices=Approval.choices, default=Approval.NOT_REQUESTED
    )
    registration_fee_minor = models.PositiveIntegerField(default=0)
    registration_fee_currency = models.CharField(max_length=3, default="KES")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    # The organizers let ready matches go to free tables by themselves, in queue order (REQ-014).
    auto_dispatch = models.BooleanField(default=False)
    # A published match moved by more than this many minutes, or to another table, is news for its
    # players and umpire (REQ-043).
    schedule_notice_minutes = models.PositiveSmallIntegerField(default=15)
    # When the published order of play becomes public (REQ-053): no earlier than three days before the
    # first day's start. Set when the schedule is first published; until then only staff see times.
    order_of_play_release_at = models.DateTimeField(null=True, blank=True)
    order_of_play_announced_at = models.DateTimeField(null=True, blank=True)
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


MAX_DOCUMENTS = 10


class TournamentDocument(models.Model):
    """A PDF with further details of a tournament: its prospectus, rules or entry form (REQ-007). Seen by
    whoever sees the tournament."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=120)
    file = models.OneToOneField(Attachment, on_delete=models.CASCADE, related_name="tournament_document")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.title


class Event(models.Model):
    """One competition within a tournament: who enters (players, pairs or teams) and how it is played
    (REQ-007). `revision` counts configuration changes, so a published configuration can be told apart
    from a later one."""

    class Kind(models.TextChoices):
        SINGLES = "singles"
        DOUBLES = "doubles"
        TEAM = "team"
        # Mixed doubles round robin: players enter alone, in the men's or women's pool, and play every
        # round with a different partner from the other pool (TASK-100).
        JUMBLES = "jumbles"

    class Admission(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

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
        "admission",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    format = models.CharField(max_length=16, choices=Format.choices)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)  # entries; null = no limit
    best_of = models.PositiveSmallIntegerField(default=5)
    rest_minutes = models.PositiveSmallIntegerField(default=10)
    # How long a called player has to report at the table before they are flagged (REQ-043).
    call_grace_minutes = models.PositiveSmallIntegerField(default=10)
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)
    admission = models.CharField(max_length=6, choices=Admission.choices, default=Admission.CLOSED)
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
        APPROVAL_REQUESTED = "approval_requested"
        APPROVAL_REJECTED = "approval_rejected"
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
        # A Jumbles round's pair, made by the draw: a man and a woman who play one match together.
        PAIRING = "pairing"

    class Pool(models.TextChoices):
        MEN = "men", "Men"
        WOMEN = "women", "Women"

    # Statuses in which the entry still stands, so its players can't be in another entry of the event.
    LIVE = (Status.PENDING, Status.ACCEPTED, Status.WAITLISTED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="entries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    team_name = models.CharField(max_length=80, blank=True)  # team events only
    pool = models.CharField(max_length=5, choices=Pool.choices, blank=True)  # Jumbles entries only
    # A pairing belongs to the draw that made it, and goes when that draw is replaced.
    pairing_draw = models.ForeignKey(
        "DrawVersion", on_delete=models.CASCADE, null=True, blank=True, related_name="pairings"
    )
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
    checked_in_at = models.DateTimeField(null=True, blank=True)

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
    # What the organizers chose to keep apart in the groups ("clubs", "teams", "regions") and the most
    # entries of one a group may hold. Publication checks the draw against the same choice.
    keep_apart = ArrayField(models.CharField(max_length=8), default=list, blank=True)
    same_group_limit = models.PositiveSmallIntegerField(default=3)
    # The last time the organizers moved an entry of this draw by hand. A moved draw is no longer what
    # `rng_seed` alone gives.
    moved_at = models.DateTimeField(null=True, blank=True)
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

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
        DISQUALIFIED = "disqualified"  # the referee disqualified the loser, before or during play

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
    outcome = models.CharField(max_length=12, choices=Outcome.choices, blank=True)
    games = models.JSONField(default=list, blank=True)
    # Where and when it is expected to be played; both empty until the organizers schedule it. The time
    # is an estimate, never a promise (REQ-014).
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    # The table the day schedule plans it for (TASK-099). `table` is where it is actually sent, which a
    # recall clears; the plan stays, and the dispatch board offers this table first when it is free.
    planned_table = models.ForeignKey(
        Table, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The organizers' working plan (TASK-081): edited freely, and copied into `planned_table` and
    # `scheduled_at`, which everybody else sees, only when they publish the schedule.
    draft_table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    draft_at = models.DateTimeField(null=True, blank=True)
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
    outcome = models.CharField(max_length=12, choices=Match.Outcome.choices, blank=True)
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
    # Results are the record: a match that has one can't be deleted from under it.
    match = models.ForeignKey(Match, on_delete=models.PROTECT, related_name="results")
    rubber = models.ForeignKey(
        Rubber, on_delete=models.PROTECT, null=True, blank=True, related_name="results"
    )
    version = models.PositiveSmallIntegerField(default=1)
    winner = models.ForeignKey(Entry, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=12, choices=Match.Outcome.choices)
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
        WITHDRAWN = "withdrawn"  # a later correction overtook the question before anyone decided

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="resolutions")
    match = models.ForeignKey(Match, on_delete=models.PROTECT, related_name="resolutions")
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


class ScheduleSession(models.Model):
    """A block of one day's play (REQ-043): its hours, the tables in use and the events it is for. No
    events chosen means every event. The recommended schedule fills sessions, earliest first."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="schedule_sessions")
    name = models.CharField(max_length=80, blank=True)
    day = models.DateField()
    starts = models.TimeField()
    ends = models.TimeField()
    tables = models.ManyToManyField(Table, related_name="+")
    events = models.ManyToManyField(Event, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["day", "starts", "created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends__gt=models.F("starts")), name="session_ends_after_start"
            )
        ]

    def __str__(self):
        return f"{self.day} {self.starts}-{self.ends}"


class ScheduleVersion(models.Model):
    """One publication of the day schedule (REQ-043): every planned match as it stood, and what changed
    from the version before. Versions are never edited; a later change is a later version."""

    class Kind(models.TextChoices):
        PUBLISHED = "published"  # the organizers published their plan
        DELAY = "delay"  # a table started late or went out of service
        MOVED = "moved"  # a match, or a player's matches, moved later
        SET = "set"  # staff set one match's table and start by hand, published at once

    class Reason(models.TextChoices):
        LATE_START = "late_start", "Late start"
        OUT_OF_SERVICE = "out_of_service", "Table out of service"
        PLAYER_REQUEST = "player_request", "A player's request"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="schedule_versions")
    number = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    reason = models.CharField(max_length=14, choices=Reason.choices, blank=True)
    note = models.CharField(max_length=300, blank=True)
    delayed_table = models.ForeignKey(
        Table, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    delay_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    # Every match still to play as published: match id, label, title, table id and label, start.
    slots = models.JSONField(default=list)
    # The matches whose table or start changed: before and after, and whether its people are told.
    changes = models.JSONField(default=list)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    published_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    notified_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["tournament", "number"], name="one_schedule_version_number")
        ]

    def __str__(self):
        return f"{self.tournament_id} v{self.number}"


class StageOrder(models.Model):
    """One place in a tournament's order of play (REQ-053): an event's group or knockout stage. Dispatch
    and the recommended schedule take stages in this order, falling through to a later stage whose
    players are free rather than leave a table idle."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="stage_order")
    position = models.PositiveSmallIntegerField()
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="+")
    stage = models.CharField(max_length=10, choices=Match.Stage.choices)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["tournament", "event", "stage"], name="one_place_per_stage")
        ]

    def __str__(self):
        return f"{self.position}: {self.event_id} {self.stage}"


class NotBefore(models.Model):
    """A player who can't play before a time on a tournament day (REQ-053): their matches are planned
    and sent no earlier, unless staff set it aside with a reason."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="not_before")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    at = models.DateTimeField()
    note = models.CharField(max_length=200, blank=True)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    set_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["tournament", "user"], name="one_not_before_per_player")
        ]

    def __str__(self):
        return f"{self.user_id} not before {self.at}"


class TournamentReview(models.Model):
    """What the host learned from a tournament (REQ-055): what went well, what went wrong and what to do
    next time. Written by the host's competition staff once it is over; read by them and by the officials
    of its region and country. Never public."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.OneToOneField(Tournament, on_delete=models.CASCADE, related_name="review")
    went_well = models.TextField(max_length=5000, blank=True)
    went_wrong = models.TextField(max_length=5000, blank=True)
    # What to do next time: a list of {"text": str, "owner": str, "due_on": date | null, "done": bool}.
    # The owner is a name as staff wrote it: it may be someone without an account.
    actions = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Review of {self.tournament_id}"


class Ceremony(models.Model):
    """A tournament's award ceremony (REQ-018, REQ-049): when and where it is held and the awards it
    gives, in the order they are presented. A draft is for the host's competition staff; once published
    everyone who sees the tournament sees it."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        DONE = "done"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.OneToOneField(Tournament, on_delete=models.CASCADE, related_name="ceremony")
    starts_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    host = models.CharField(max_length=120, blank=True)  # the master of ceremonies
    notes = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ceremony of {self.tournament_id}"


class Award(models.Model):
    """One award of a ceremony: a place in an event, taken from its results, or an award the organizers
    give (best player, fair play, a sponsor's prize). Who receives it is the entry that placed, a player,
    or a name for someone without an account."""

    class Kind(models.TextChoices):
        PLACEMENT = "placement"
        SPECIAL = "special"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ceremony = models.ForeignKey(Ceremony, on_delete=models.CASCADE, related_name="awards")
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SPECIAL)
    title = models.CharField(max_length=120)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    place = models.PositiveSmallIntegerField(null=True, blank=True)
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="awards"
    )
    recipient_name = models.CharField(max_length=120, blank=True)
    prize = models.CharField(max_length=200, blank=True)  # medal, trophy, cash or goods
    presenter = models.CharField(max_length=120, blank=True)  # who hands it over
    presented_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind="special")
                | models.Q(event__isnull=False, place__isnull=False, entry__isnull=False),
                name="placement_award_has_place",
            ),
        ]

    def __str__(self):
        return self.title


class LiveStream(models.Model):
    """A link to watch a tournament, or one of its matches, on another site: YouTube, Facebook, TikTok and
    the like (REQ-042). Coast TT only links: it neither hosts nor embeds the video. Links are https and
    open in a new tab with their site shown; anyone who sees the tournament can report one."""

    class Platform(models.TextChoices):
        YOUTUBE = "youtube", "YouTube"
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        TIKTOK = "tiktok", "TikTok"
        TWITCH = "twitch", "Twitch"
        X = "x", "X"
        KICK = "kick", "Kick"
        OTHER = "other", "Other site"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="streams")
    match = models.ForeignKey(Match, on_delete=models.CASCADE, null=True, blank=True, related_name="streams")
    url = models.URLField(max_length=500)
    platform = models.CharField(max_length=10, choices=Platform.choices)
    title = models.CharField(max_length=80, blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.platform} {self.url}"


class LiveStreamReport(models.Model):
    """Somebody says a stream link is wrong. One report per person and link; reporting again updates it."""

    class Reason(models.TextChoices):
        BROKEN = "broken", "Doesn't work"
        WRONG = "wrong", "Wrong match or event"
        INAPPROPRIATE = "inappropriate", "Inappropriate or unsafe"
        OTHER = "other", "Something else"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stream = models.ForeignKey(LiveStream, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=14, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["stream", "reporter"], name="one_report_per_person_and_stream")
        ]

    def __str__(self):
        return f"{self.reason} on {self.stream_id}"


class MatchDayLog(models.Model):
    """One staff action on match day (REQ-043): who did what, when and why. Calls, recalls, moves,
    players reporting, check-ins, umpire assignments, tables blocked, results entered and corrected.
    Entries are only ever added."""

    class Action(models.TextChoices):
        CALLED = "called", "Called to a table"
        CALLED_AGAIN = "called_again", "Called again"
        RECALLED = "recalled", "Taken off the table"
        MOVED = "moved", "Moved to another table"
        REPORTED = "reported", "Reported at the table"
        REPORT_UNDONE = "report_undone", "Report undone"
        CHECKED_IN = "checked_in", "Checked in"
        CHECK_IN_UNDONE = "check_in_undone", "Check-in undone"
        UMPIRE_ASSIGNED = "umpire_assigned", "Umpire assigned"
        UMPIRE_REMOVED = "umpire_removed", "Umpire taken off"
        TABLE_BLOCKED = "table_blocked", "Table blocked"
        TABLE_UNBLOCKED = "table_unblocked", "Table back in use"
        RESULT_ENTERED = "result_entered", "Result entered"
        RESULT_CORRECTED = "result_corrected", "Result corrected"
        CORRECTION_SETTLED = "correction_settled", "Later match settled after a correction"
        AUTO_ON = "auto_on", "Automatic dispatch switched on"
        AUTO_OFF = "auto_off", "Automatic dispatch switched off"
        UMPIRE_LISTED = "umpire_listed", "Added to the umpires"
        UMPIRE_UNLISTED = "umpire_unlisted", "Taken off the umpires"
        TABLE_UMPIRE = "table_umpire", "Table umpire changed"
        ORDER_CHANGED = "order_changed", "Order of play changed"
        NOT_BEFORE = "not_before", "Player's start time set"
        MATCH_MOVED = "match_moved", "Match moved later"
        MATCH_TIMED = "match_timed", "Match time set"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="match_day_log")
    match = models.ForeignKey(Match, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    # What it was about, in words as it stood then: the match, the table, the player, the outcome.
    summary = models.CharField(max_length=300)
    reason = models.CharField(max_length=300, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["tournament", "-at"], name="match_day_log_recent")]

    def __str__(self):
        return f"{self.action} at {self.at}"


class Announcement(models.Model):
    """A results announcement (REQ-043, TASK-085): text the generator drafts from official results for a
    session, round, day, event or the whole tournament, edited by the organizers and published to the
    tournament's news feed. A published one is frozen. A later correction to a result it covers marks it
    outdated; an amendment is a new announcement that names the one it amends, which stays visible."""

    class Scope(models.TextChoices):
        SESSION = "session"
        ROUND = "round"
        DAY = "day"
        EVENT = "event"
        TOURNAMENT = "tournament"

    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="announcements")
    scope = models.CharField(max_length=10, choices=Scope.choices)
    # What the scope is: the event (event and round), the round's stage and number, the day, the session.
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    stage = models.CharField(max_length=10, choices=Match.Stage.choices, blank=True)
    round = models.PositiveSmallIntegerField(null=True, blank=True)
    day = models.DateField(null=True, blank=True)
    session = models.ForeignKey(
        ScheduleSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    title = models.CharField(max_length=120)
    body = models.TextField()
    # The matches the text was drawn from: a correction to any of them outdates a published post.
    covers = models.ManyToManyField(Match, related_name="announcements", blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    amends = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="amendments"
    )
    outdated_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["tournament", "status", "-published_at"], name="announcement_feed"),
        ]

    def __str__(self):
        return self.title
