from zoneinfo import ZoneInfo

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from core.money import MAX_AMOUNT_MINOR
from core.timezones import validate_timezone
from facilities.models import Venue
from facilities.serializers import VenueSummarySerializer
from organizations.models import Organization
from scoring.serializers import ScoringSummarySerializer

from .draws import MAX_SEEDS
from .models import (
    DEFAULT_TIE_RUBBERS,
    MAX_TEAM_ROSTER,
    MAX_TIE_RUBBERS,
    DrawVersion,
    Entry,
    EntryPlayer,
    Event,
    LifecycleEntry,
    Match,
    Rubber,
    Tournament,
)

BEST_OF = (3, 5, 7)
MAX_CAPACITY = 512
MAX_REST_MINUTES = 240
MAX_GROUPS = 64
MAX_QUALIFIERS = 8


@extend_schema_serializer(component_name="Money")
class EntryFeeSerializer(serializers.Serializer):
    """The event's declared entry fee in the REQ-032 money shape."""

    amount_minor = serializers.IntegerField(source="entry_fee_minor", min_value=0, max_value=MAX_AMOUNT_MINOR)
    currency = serializers.RegexField(r"^[A-Z]{3}$", source="entry_fee_currency", default="KES")


class EventSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    entry_fee = EntryFeeSerializer(source="*", required=False)
    capacity = serializers.IntegerField(min_value=2, max_value=MAX_CAPACITY, allow_null=True, required=False)
    best_of = serializers.ChoiceField(choices=BEST_OF, required=False)
    rest_minutes = serializers.IntegerField(min_value=0, max_value=MAX_REST_MINUTES, required=False)
    group_count = serializers.IntegerField(min_value=2, max_value=MAX_GROUPS, allow_null=True, required=False)
    qualifiers_per_group = serializers.IntegerField(
        min_value=1, max_value=MAX_QUALIFIERS, allow_null=True, required=False
    )
    tie_rubbers = serializers.ListField(
        child=serializers.ChoiceField(choices=Rubber.Kind.choices),
        max_length=MAX_TIE_RUBBERS,
        required=False,
        help_text="Team events: the individual matches of a tie in playing order. Empty otherwise.",
    )
    tie_wins_needed = serializers.IntegerField(
        min_value=1,
        max_value=MAX_TIE_RUBBERS,
        allow_null=True,
        required=False,
        help_text="Team events: rubbers a team must win to take the tie; at most half of them, rounded "
        "up, so a tie always has a winner. Null otherwise.",
    )
    accepted_count = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "name",
            "kind",
            "format",
            "capacity",
            "best_of",
            "rest_minutes",
            "registration_opens_at",
            "registration_closes_at",
            "entry_fee",
            "seeding",
            "group_count",
            "qualifiers_per_group",
            "tie_rubbers",
            "tie_wins_needed",
            "accepted_count",
            "status",
            "revision",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]
        read_only_fields = [
            "id",
            "status",
            "revision",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]

    def get_accepted_count(self, event) -> int:
        """Entries holding a place. Counted here when the caller didn't annotate it."""
        counted = getattr(event, "accepted_count", None)
        return event.entries.filter(status=Entry.Status.ACCEPTED).count() if counted is None else counted

    def validate(self, attrs):
        def current(name):
            return attrs[name] if name in attrs else getattr(self.instance, name, None)

        # What the caller asked to change in the structure, before the clean-up below can hide it.
        self.structure_changes = {
            name
            for name in Event.STRUCTURE_FIELDS
            if self.instance is not None and name in attrs and attrs[name] != getattr(self.instance, name)
        }

        if current("format") == Event.Format.GROUPS_KNOCKOUT:
            groups, qualifiers, capacity = (
                current("group_count"),
                current("qualifiers_per_group"),
                current("capacity"),
            )
            errors = {}
            if groups is None:
                errors["group_count"] = "Say how many groups there are."
            if qualifiers is None:
                errors["qualifiers_per_group"] = "Say how many from each group go through."
            if errors:
                raise serializers.ValidationError(errors)
            # Every group needs at least one entry more than the number that qualify from it.
            if capacity is not None and capacity < groups * (qualifiers + 1):
                raise serializers.ValidationError(
                    {
                        "capacity": f"{groups} groups sending {qualifiers} through need at least "
                        f"{groups * (qualifiers + 1)} entries."
                    }
                )
        else:
            # Groups and qualifiers only mean something for groups followed by a knockout.
            attrs["group_count"] = None
            attrs["qualifiers_per_group"] = None

        if current("kind") == Event.Kind.TEAM:
            # A team event always has a tie format; left out, it is the usual four singles and a doubles.
            rubbers = current("tie_rubbers") or list(DEFAULT_TIE_RUBBERS)
            wins = attrs.get("tie_wins_needed")
            if wins is None and "tie_rubbers" not in attrs:
                wins = getattr(self.instance, "tie_wins_needed", None)
            most = (len(rubbers) + 1) // 2
            if wins is None:
                wins = most
            # A tie must always produce a winner: with both teams one short of the wins needed there
            # is still a rubber left to play, so 2 x wins - 1 can't exceed the number of rubbers.
            if wins > most:
                raise serializers.ValidationError(
                    {
                        "tie_wins_needed": f"With {len(rubbers)} rubbers a tie is won with at most {most} "
                        "wins: more could leave it without a winner."
                    }
                )
            attrs["tie_rubbers"], attrs["tie_wins_needed"] = rubbers, wins
        else:
            attrs["tie_rubbers"], attrs["tie_wins_needed"] = [], None

        opens, closes = current("registration_opens_at"), current("registration_closes_at")
        if opens and closes and closes <= opens:
            raise serializers.ValidationError(
                {"registration_closes_at": "Registration must close after it opens."}
            )
        tournament = self.context.get("tournament") or getattr(self.instance, "tournament", None)
        if (
            closes
            and tournament
            and closes.astimezone(ZoneInfo(tournament.timezone)).date() > tournament.ends_on
        ):
            raise serializers.ValidationError(
                {"registration_closes_at": "Registration must close by the tournament's last day."}
            )
        return attrs


class OrganizationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "town"]
        read_only_fields = fields


class TournamentSerializer(serializers.ModelSerializer):
    """A tournament with its events. The same fields serve staff and the public (REQ-020): nothing here
    is private once the tournament is published, and drafts are served to the host's staff only."""

    name = serializers.CharField(max_length=120, trim_whitespace=True)
    description = serializers.CharField(
        max_length=2000, trim_whitespace=True, allow_blank=True, required=False
    )
    organization = OrganizationSummarySerializer(read_only=True)
    venue = VenueSummarySerializer(read_only=True, allow_null=True)
    venue_id = serializers.PrimaryKeyRelatedField(
        source="venue", queryset=Venue.objects.all(), write_only=True, allow_null=True, required=False
    )
    timezone = serializers.CharField(max_length=64, required=False, validators=[validate_timezone])
    events = EventSerializer(many=True, read_only=True)

    class Meta:
        model = Tournament
        fields = [
            "id",
            "organization",
            "venue",
            "venue_id",
            "name",
            "description",
            "starts_on",
            "ends_on",
            "timezone",
            "status",
            "published_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
            "events",
        ]
        read_only_fields = [
            "id",
            "status",
            "published_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]

    def validate_venue_id(self, venue):
        """The venue must be one of the host's own and in use (a tournament may keep the one it has)."""
        if venue is None:
            if self.instance is not None and self.instance.status != Tournament.Status.DRAFT:
                raise serializers.ValidationError("A published tournament keeps a venue.")
            return venue
        unchanged = self.instance is not None and self.instance.venue_id == venue.id
        organization = self.context["organization"]
        if venue.organization_id != organization.id or not (venue.active or unchanged):
            raise serializers.ValidationError("Choose one of this organization's venues.")
        return venue

    def validate(self, attrs):
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "The last day can't be before the first day."})
        return attrs


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class LifecycleEntrySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default="")

    class Meta:
        model = LifecycleEntry
        fields = ["id", "action", "event_name", "actor_name", "reason", "snapshot", "created_at"]
        read_only_fields = fields


class EntryPlayerSerializer(serializers.ModelSerializer):
    """A player in an entry: the name they play under, nothing else (REQ-020)."""

    id = serializers.UUIDField(source="user_id", read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)

    class Meta:
        model = EntryPlayer
        fields = ["id", "display_name"]
        read_only_fields = fields


class EntrySerializer(serializers.ModelSerializer):
    """An entry as its players, staff and (once accepted) everybody else see it. Deliberately nothing
    about payment: accepted means a place in the event, not a paid fee (REQ-008)."""

    players = EntryPlayerSerializer(many=True, read_only=True)
    captain_id = serializers.UUIDField(read_only=True, allow_null=True)
    mine = serializers.SerializerMethodField()

    class Meta:
        model = Entry
        fields = [
            "id",
            "status",
            "players",
            "team_name",
            "captain_id",
            "reason",
            "created_at",
            "decided_at",
            "withdrawn_at",
            "checked_in_at",
            "mine",
        ]
        read_only_fields = fields

    def get_mine(self, entry) -> bool:
        """Whether the caller plays in it, so may withdraw it."""
        user = self.context["request"].user
        return any(place.user_id == user.id for place in entry.players.all())


class EntryEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "name", "kind", "status"]
        read_only_fields = fields


class EntryTournamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tournament
        fields = ["id", "name", "starts_on", "ends_on", "timezone", "status"]
        read_only_fields = fields


class MyEntrySerializer(EntrySerializer):
    """One of the caller's own entries, with the event and tournament it is for."""

    event = EntryEventSerializer(read_only=True)
    tournament = EntryTournamentSerializer(source="event.tournament", read_only=True)

    class Meta(EntrySerializer.Meta):
        fields = [*EntrySerializer.Meta.fields, "event", "tournament"]
        read_only_fields = fields


class EntryRequestSerializer(serializers.Serializer):
    """Who is entering. Left out, `player_ids` is the caller alone and `captain_id` the caller."""

    player_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_TEAM_ROSTER, required=False
    )
    team_name = serializers.CharField(max_length=80, trim_whitespace=True, allow_blank=True, required=False)
    captain_id = serializers.UUIDField(allow_null=True, required=False)

    def validate_player_ids(self, ids):
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Each player can be in the entry once.")
        return ids


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True, allow_blank=True, required=False)


class DrawEntrySerializer(serializers.ModelSerializer):
    """An accepted entry as a draw shows it: its name and players."""

    title = serializers.SerializerMethodField()
    players = EntryPlayerSerializer(many=True, read_only=True)
    mine = serializers.SerializerMethodField()

    class Meta:
        model = Entry
        fields = ["id", "title", "players", "mine"]
        read_only_fields = fields

    def get_mine(self, entry) -> bool:
        """Whether the caller plays in it, so screens can point out their own matches."""
        user = self.context["request"].user
        return any(place.user_id == user.id for place in entry.players.all())

    def get_title(self, entry) -> str:
        return entry.team_name or " / ".join(place.user.display_name for place in entry.players.all())


class DrawPlaceSerializer(serializers.Serializer):
    entry = DrawEntrySerializer()
    seed = serializers.IntegerField(allow_null=True)
    group = serializers.IntegerField(allow_null=True)
    group_position = serializers.IntegerField(allow_null=True)
    bracket_position = serializers.IntegerField(allow_null=True)


class MatchSideSerializer(serializers.Serializer):
    """An entry, or (while `entry` is null) `awaiting` says whose place it is, e.g. "Winner of
    semi-final 1" or "Group A winner"."""

    entry = DrawEntrySerializer(allow_null=True)
    seed = serializers.IntegerField(allow_null=True)
    awaiting = serializers.CharField(allow_blank=True)


class MatchSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    stage = serializers.ChoiceField(choices=Match.Stage.choices)
    group = serializers.IntegerField(allow_null=True)
    round = serializers.IntegerField()
    round_name = serializers.CharField()
    position = serializers.IntegerField()
    a = MatchSideSerializer()
    b = MatchSideSerializer(allow_null=True, help_text="Null is a bye: `a` goes through without playing.")
    status = serializers.ChoiceField(choices=Match.Status.choices)
    winner_id = serializers.UUIDField(allow_null=True)
    outcome = serializers.ChoiceField(choices=Match.Outcome.choices, allow_blank=True)
    games = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2),
        help_text="Points of each game as [a, b], in playing order.",
    )
    tie_score = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=2,
        max_length=2,
        allow_null=True,
        help_text="Team ties that have begun: rubbers won as [a, b]. Null otherwise.",
    )
    table = serializers.CharField(allow_blank=True, help_text="The table's label; empty until one is given.")
    scheduled_at = serializers.DateTimeField(
        allow_null=True, help_text="When it is expected to start: an estimate. Null until it is scheduled."
    )
    dispatched_at = serializers.DateTimeField(
        allow_null=True, help_text="When it was sent to its table. Null while it isn't on one."
    )


class LineupSideSerializer(serializers.Serializer):
    """Where one team's lineup stands. `picks` are given to the team itself and to staff until both
    lineups are in; after that the rubbers show who plays."""

    submitted = serializers.BooleanField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    can_submit = serializers.BooleanField(help_text="The caller may hand in or replace this lineup now.")
    picks = serializers.ListField(
        child=serializers.ListField(child=serializers.UUIDField()),
        allow_null=True,
        help_text="Player ids for each rubber of the template, in order.",
    )


class RubberPlayerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class RubberSerializer(serializers.Serializer):
    """One individual match of a tie. `not_played` means the tie was decided before its turn."""

    id = serializers.UUIDField()
    position = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=Rubber.Kind.choices)
    status = serializers.ChoiceField(choices=Rubber.Status.choices)
    a_players = RubberPlayerSerializer(many=True)
    b_players = RubberPlayerSerializer(many=True)
    winner_id = serializers.UUIDField(allow_null=True, help_text="The entry (team) that won it.")
    outcome = serializers.ChoiceField(choices=Match.Outcome.choices, allow_blank=True)
    games = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    )
    scoring = ScoringSummarySerializer()


class TieSerializer(serializers.Serializer):
    """A team tie (REQ-011): its format, each team's lineup and, once both are in, its rubbers."""

    wins_needed = serializers.IntegerField()
    template = serializers.ListField(child=serializers.ChoiceField(choices=Rubber.Kind.choices))
    begun = serializers.BooleanField(help_text="Both lineups are in and the rubbers exist.")
    score = serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    a = LineupSideSerializer()
    b = LineupSideSerializer()
    can_reset = serializers.BooleanField(help_text="The caller may send both teams back to choose again.")
    rubbers = RubberSerializer(many=True)


class LineupRequestSerializer(serializers.Serializer):
    """A team's players for each rubber of the tie, in the template's order: one id for a singles, two
    for a doubles."""

    entry_id = serializers.UUIDField()
    picks = serializers.ListField(
        child=serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=2),
        max_length=MAX_TIE_RUBBERS,
    )


class OnTableSerializer(serializers.Serializer):
    """The match is on a table: the table and its players are held until the result is official."""

    table = serializers.CharField()
    since = serializers.DateTimeField()
    people = serializers.ListField(child=serializers.CharField())
    waiting_for = serializers.ListField(
        child=serializers.CharField(),
        help_text="Players of the tie's current rubber who are in use elsewhere (staff only).",
    )


class MatchDetailSerializer(MatchSerializer):
    """One match of the published draw on its own page. Reading it gives nobody a way to score it."""

    group_name = serializers.CharField(allow_blank=True, help_text="Empty for a knockout match.")
    winner_plays_in = serializers.CharField(
        allow_blank=True, help_text="The round its winner goes on to; empty when nothing follows."
    )
    draw_version = serializers.IntegerField()
    tie = TieSerializer(allow_null=True, help_text="Team events only.")
    scoring = ScoringSummarySerializer(allow_null=True, help_text="Null for a tie: its rubbers are scored.")
    on_table = OnTableSerializer(allow_null=True)
    can_dispatch = serializers.BooleanField(help_text="The caller may send it to a table or call it back.")


class DrawGroupSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    name = serializers.CharField()


class DrawSerializer(serializers.Serializer):
    """One version of an event's draw: who sits where, and every match with its sides."""

    id = serializers.UUIDField()
    version = serializers.IntegerField()
    status = serializers.ChoiceField(choices=DrawVersion.Status.choices)
    rules_version = serializers.CharField()
    rng_seed = serializers.IntegerField()
    stale = serializers.BooleanField(
        help_text="The accepted entries or the event's format changed since this draw was made."
    )
    created_at = serializers.DateTimeField()
    published_at = serializers.DateTimeField(allow_null=True)
    groups = DrawGroupSerializer(many=True)
    places = DrawPlaceSerializer(many=True)
    matches = MatchSerializer(many=True)


class EventDrawSerializer(serializers.Serializer):
    """The event's published draw and, for competition staff only, the preview being worked on."""

    published = DrawSerializer(allow_null=True)
    preview = DrawSerializer(allow_null=True)


class DrawRequestSerializer(serializers.Serializer):
    """Seeds in order, best first (accepted entries of the event). `rng_seed` repeats an earlier draw."""

    seeded_entry_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=MAX_SEEDS, required=False
    )
    rng_seed = serializers.IntegerField(min_value=0, max_value=2**31 - 1, required=False)


class TieBreakStepSerializer(serializers.Serializer):
    """One comparison made between members who were level, up to the one that separated them (or the
    lot): the entries compared, what on
    (`match_points`, `rubbers`, `games`, `points` won/lost between them, or `lot`) and this row's value."""

    among = serializers.ListField(child=serializers.UUIDField())
    measure = serializers.ChoiceField(choices=["match_points", "rubbers", "games", "points", "lot"])
    value = serializers.CharField(allow_blank=True)


class StandingRowSerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    entry = DrawEntrySerializer()
    played = serializers.IntegerField()
    won = serializers.IntegerField()
    lost = serializers.IntegerField()
    match_points = serializers.IntegerField()
    games_won = serializers.IntegerField()
    games_lost = serializers.IntegerField()
    points_won = serializers.IntegerField()
    points_lost = serializers.IntegerField()
    level = serializers.BooleanField(
        help_text="Not yet separated from a neighbouring row; the group isn't finished."
    )
    qualified = serializers.BooleanField(
        allow_null=True, help_text="Null until the group is finished, and always in a round robin event."
    )
    tie_break = TieBreakStepSerializer(many=True)


class GroupStandingSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    name = serializers.CharField()
    complete = serializers.BooleanField()
    qualifiers = serializers.IntegerField(help_text="How many go through; 0 for a round robin event.")
    rows = StandingRowSerializer(many=True)


class PlacementSerializer(serializers.Serializer):
    label = serializers.CharField()
    entries = DrawEntrySerializer(many=True)


class StandingsSerializer(serializers.Serializer):
    """Group tables with the reason for every separated tie, and what the knockout has decided."""

    rules_version = serializers.CharField(allow_blank=True)
    groups = GroupStandingSerializer(many=True)
    placements = PlacementSerializer(many=True)
