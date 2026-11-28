from zoneinfo import ZoneInfo

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from attachments.serializers import AttachmentLinkSerializer
from core.money import MAX_AMOUNT_MINOR
from core.timezones import validate_timezone
from facilities.models import Venue
from facilities.serializers import VenueSummarySerializer
from organizations.models import Organization
from profiles.serializers import PlayerSerializer
from scoring.serializers import ScoringSummarySerializer

from . import formats
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
    OfficialResult,
    Resolution,
    Rubber,
    Tournament,
    TournamentDocument,
)

BEST_OF = (3, 5, 7)
MAX_CAPACITY = 512
MAX_REST_MINUTES = 240
MAX_GRACE_MINUTES = 60
MAX_GROUPS = 64
MAX_QUALIFIERS = 8


@extend_schema_serializer(component_name="Money")
class EntryFeeSerializer(serializers.Serializer):
    """The event's declared entry fee in the REQ-032 money shape."""

    amount_minor = serializers.IntegerField(source="entry_fee_minor", min_value=0, max_value=MAX_AMOUNT_MINOR)
    currency = serializers.RegexField(r"^[A-Z]{3}$", source="entry_fee_currency", default="KES")


class RegistrationFeeSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField(
        source="registration_fee_minor", min_value=0, max_value=MAX_AMOUNT_MINOR
    )
    currency = serializers.RegexField(r"^[A-Z]{3}$", source="registration_fee_currency", default="KES")


class EventSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    entry_fee = EntryFeeSerializer(source="*", required=False)
    capacity = serializers.IntegerField(min_value=2, max_value=MAX_CAPACITY, allow_null=True, required=False)
    best_of = serializers.ChoiceField(choices=BEST_OF, required=False)
    best_of_by_stage = serializers.DictField(
        child=serializers.ChoiceField(choices=BEST_OF),
        required=False,
        help_text="Longer matches as the event goes on: best of 3, 5 or 7 for any of `group`, `knockout` "
        "(rounds before the quarter-finals), `quarter_final`, `semi_final`, `final`. A knockout stage not "
        "given plays as the one before it; the rest play `best_of`.",
    )
    rest_minutes = serializers.IntegerField(min_value=0, max_value=MAX_REST_MINUTES, required=False)
    call_grace_minutes = serializers.IntegerField(
        min_value=1,
        max_value=MAX_GRACE_MINUTES,
        required=False,
        help_text="Minutes a called player has to report at the table before the control centre flags "
        "them as a no-show (REQ-043). Only the referee then awards a walkover.",
    )
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
    matches_left = serializers.SerializerMethodField(
        help_text="Matches of the published draw with no result yet. The event can't be completed while any "
        "is left."
    )

    class Meta:
        model = Event
        fields = [
            "id",
            "name",
            "kind",
            "format",
            "capacity",
            "best_of",
            "best_of_by_stage",
            "rest_minutes",
            "call_grace_minutes",
            "registration_opens_at",
            "registration_closes_at",
            "admission",
            "entry_fee",
            "seeding",
            "group_count",
            "qualifiers_per_group",
            "tie_rubbers",
            "tie_wins_needed",
            "accepted_count",
            "matches_left",
            "status",
            "revision",
            "paused_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]
        read_only_fields = [
            "id",
            "status",
            "revision",
            "paused_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]

    def get_matches_left(self, event) -> int:
        counted = getattr(event, "matches_left", None)
        return event.count_matches_left() if counted is None else counted

    def get_accepted_count(self, event) -> int:
        """Entries holding a place. Counted here when the caller didn't annotate it."""
        counted = getattr(event, "accepted_count", None)
        return event.entries.filter(status=Entry.Status.ACCEPTED).count() if counted is None else counted

    def validate_best_of_by_stage(self, value):
        problem = formats.stage_problem(value)
        if problem:
            raise serializers.ValidationError(problem)
        return value

    def validate(self, attrs):
        def current(name):
            return attrs[name] if name in attrs else getattr(self.instance, name, None)

        # Only the stages the format has: no groups in a knockout, no knockout in a round robin.
        if "best_of_by_stage" in attrs or "format" in attrs:
            stages = current("best_of_by_stage") or {}
            kept = {
                formats.GROUP: current("format") in (Event.Format.ROUND_ROBIN, Event.Format.GROUPS_KNOCKOUT),
                **dict.fromkeys(formats.KNOCKOUT_STAGES, current("format") != Event.Format.ROUND_ROBIN),
            }
            attrs["best_of_by_stage"] = {key: games for key, games in stages.items() if kept[key]}

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

        if current("kind") == Event.Kind.JUMBLES:
            if current("format") != Event.Format.ROUND_ROBIN:
                raise serializers.ValidationError({"format": "Jumbles is played as a round robin."})
            attrs["seeding"] = Event.Seeding.NONE  # partners and opponents rotate, so nobody is seeded

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
        fields = ["id", "name", "town", "country", "region"]
        read_only_fields = fields


class OrganizerSerializer(serializers.Serializer):
    """Who a tournament is organized by, as players should read it: the host club, facility or regional
    body by name, or for a coach's tournament the coach or their firm."""

    name = serializers.CharField()
    kind = serializers.ChoiceField(
        choices=[
            "club",
            "team",
            "facility",
            "club_facility",
            "regional_body",
            "national_body",
            "coach",
            "firm",
        ]
    )
    label = serializers.CharField()


ORGANIZER_LABELS = {
    Organization.Kind.CLUB: "Club",
    Organization.Kind.TEAM: "Team",
    Organization.Kind.FACILITY: "Facility",
    Organization.Kind.CLUB_FACILITY: "Club and facility",
    Organization.Kind.REGIONAL_BODY: "Regional body",
    Organization.Kind.NATIONAL_BODY: "National body",
}


def organizer(tournament) -> dict:
    host = tournament.organization
    coach = getattr(host, "coach_organizer", None) if host.is_coaching else None
    if coach is not None:
        if tournament.presented_as == Tournament.PresentedAs.FIRM and coach.firm_name:
            return {"name": coach.firm_name, "kind": "firm", "label": "Coaching firm"}
        return {"name": coach.user.display_name, "kind": "coach", "label": "Coach"}
    if host.is_coaching:
        return {"name": host.name, "kind": "coach", "label": "Coach"}
    return {"name": host.name, "kind": host.kind, "label": ORGANIZER_LABELS.get(host.kind, "Club")}


class TournamentDocumentSerializer(serializers.ModelSerializer):
    """A document of a tournament with a fresh signed link to the PDF."""

    file = serializers.SerializerMethodField()

    class Meta:
        model = TournamentDocument
        fields = ["id", "title", "file", "created_at"]
        read_only_fields = fields

    @extend_schema_field(AttachmentLinkSerializer)
    def get_file(self, document) -> dict:
        return AttachmentLinkSerializer(document.file_id).data


class TournamentDocumentUploadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, trim_whitespace=True)
    file = serializers.FileField()


class CoverUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


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
    organizer = serializers.SerializerMethodField()
    presented_as = serializers.ChoiceField(
        choices=Tournament.PresentedAs.choices,
        required=False,
        help_text="For a coach's tournament: organized in the coach's name or their firm's.",
    )
    cover = serializers.SerializerMethodField()
    documents = TournamentDocumentSerializer(many=True, read_only=True)
    registration_fee = RegistrationFeeSerializer(source="*", required=False)
    schedule_notice_minutes = serializers.IntegerField(
        min_value=0,
        max_value=240,
        required=False,
        help_text="A published match moved by more than this, or to another table, is news for its people.",
    )

    slug = serializers.CharField(read_only=True, help_text="The public link's name: /tournaments/<slug>.")

    class Meta:
        model = Tournament
        fields = [
            "id",
            "slug",
            "organization",
            "organizer",
            "presented_as",
            "venue",
            "venue_id",
            "name",
            "description",
            "cover",
            "documents",
            "starts_on",
            "ends_on",
            "timezone",
            "scope",
            "approval_status",
            "registration_fee",
            "schedule_notice_minutes",
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
            "slug",
            "approval_status",
            "status",
            "published_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]

    @extend_schema_field(OrganizerSerializer)
    def get_organizer(self, tournament) -> dict:
        return organizer(tournament)

    @extend_schema_field(AttachmentLinkSerializer(allow_null=True))
    def get_cover(self, tournament) -> dict | None:
        return AttachmentLinkSerializer(tournament.cover_id).data if tournament.cover_id else None

    def validate_presented_as(self, value):
        """Only a coach's tournament names the coach or their firm; the firm needs its name first."""
        host = self.context["organization"]
        if not host.is_coaching:
            raise serializers.ValidationError("Only a coach's tournament names the coach or a firm.")
        coach = getattr(host, "coach_organizer", None)
        if value == Tournament.PresentedAs.FIRM and not (coach and coach.firm_name):
            raise serializers.ValidationError("Add your firm's name to your coach profile first.")
        return value

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
        if "scope" in attrs:
            organization = self.context["organization"]
            scope = attrs["scope"]
            if scope != Tournament.Scope.LOCAL and not organization.country:
                raise serializers.ValidationError({"scope": "Set the host club's country first."})
            if scope == Tournament.Scope.REGIONAL and not organization.region:
                raise serializers.ValidationError({"scope": "Set the host club's region first."})
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


class SubstituteSerializer(serializers.Serializer):
    """A player of the entry leaves and someone else plays in their place from now on (TASK-155)."""

    leaving_user_id = serializers.UUIDField()
    joining_user_id = serializers.UUIDField()
    reason = serializers.CharField(
        max_length=300, trim_whitespace=True, allow_blank=True, required=False, default=""
    )


class EntrySerializer(serializers.ModelSerializer):
    """An entry as its players, staff and (once accepted) everybody else see it. Deliberately nothing
    about payment: accepted means a place in the event, not a paid fee (REQ-008)."""

    players = EntryPlayerSerializer(many=True, read_only=True)
    captain_id = serializers.UUIDField(read_only=True, allow_null=True)
    replaced_by_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="For a replaced entry: the entry that took its place."
    )
    mine = serializers.SerializerMethodField()
    my_check_in_at = serializers.SerializerMethodField()

    class Meta:
        model = Entry
        fields = [
            "id",
            "status",
            "players",
            "team_name",
            "pool",
            "captain_id",
            "reason",
            "created_at",
            "decided_at",
            "withdrawn_at",
            "checked_in_at",
            "my_check_in_at",
            "mine",
            "replaced_by_id",
        ]
        read_only_fields = fields

    def get_mine(self, entry) -> bool:
        """Whether the caller plays in it, so may withdraw it."""
        user = self.context["request"].user
        return user.is_authenticated and any(place.user_id == user.id for place in entry.players.all())

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_my_check_in_at(self, entry):
        user = self.context["request"].user
        for place in entry.players.all():
            if user.is_authenticated and place.user_id == user.id:
                return self.fields["checked_in_at"].to_representation(
                    place.checked_in_at or entry.checked_in_at
                )
        return None


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
    pool = serializers.ChoiceField(
        choices=Entry.Pool.choices, required=False, help_text="Jumbles only: the men's or the women's pool."
    )

    def validate_player_ids(self, ids):
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Each player can be in the entry once.")
        return ids


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True, allow_blank=True, required=False)


class PlayingNowSerializer(serializers.Serializer):
    """Where the entry is playing right now, in any event of the tournament (user request, 2026-11-28)."""

    table = serializers.CharField()
    match_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    live = serializers.BooleanField(help_text="Scoring has begun; false while being called or warming up.")


class DrawEntrySerializer(serializers.ModelSerializer):
    """An accepted entry as a draw shows it: its name and players."""

    title = serializers.SerializerMethodField()
    players = EntryPlayerSerializer(many=True, read_only=True)
    mine = serializers.SerializerMethodField()
    playing = serializers.SerializerMethodField()

    class Meta:
        model = Entry
        fields = ["id", "title", "pool", "players", "mine", "playing"]
        read_only_fields = fields

    @extend_schema_field(PlayingNowSerializer(allow_null=True))
    def get_playing(self, entry):
        """The table one of its players is on now, or null. Worked out once per request and tournament."""
        from reservations import service as reservations  # reservations builds on competitions

        request = self.context["request"]
        cache = getattr(request, "_playing_now", None)
        if cache is None:
            cache = request._playing_now = {"events": {}, "tournaments": {}}
        tournament_id = cache["events"].get(entry.event_id)
        if tournament_id is None:
            tournament_id = cache["events"][entry.event_id] = (
                Event.objects.filter(pk=entry.event_id).values_list("tournament_id", flat=True).first()
            )
        found = cache["tournaments"].get(tournament_id)
        if found is None:
            found = cache["tournaments"][tournament_id] = reservations.playing_now(tournament_id)
        for place in entry.players.all():
            if place.user_id in found:
                return PlayingNowSerializer(found[place.user_id]).data
        return None

    def get_mine(self, entry) -> bool:
        """Whether the caller plays in it, so screens can point out their own matches."""
        user = self.context["request"].user
        return user.is_authenticated and any(place.user_id == user.id for place in entry.players.all())

    def get_title(self, entry) -> str:
        return entry.team_name or " / ".join(place.user.display_name for place in entry.players.all())


class DrawPlaceSerializer(serializers.Serializer):
    entry = DrawEntrySerializer()
    seed = serializers.IntegerField(allow_null=True)
    group = serializers.IntegerField(allow_null=True)
    group_position = serializers.IntegerField(allow_null=True)
    bracket_position = serializers.IntegerField(allow_null=True)
    affiliations = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        help_text="In the organizers' preview: the clubs, teams and regions of the entry's players, which "
        "the draw keeps apart. Empty everywhere else.",
    )
    withdrawn = serializers.BooleanField(
        default=False,
        help_text="In the organizers' preview: no longer accepted, to be taken out of its group.",
    )


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
    is_live = serializers.BooleanField(help_text="A match or team rubber is currently being scored.")
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
    best_of = serializers.IntegerField(help_text="Games it is played over: 3, 5 or 7, by its stage.")


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


class OfficialResultSerializer(serializers.Serializer):
    """One version of the official result of a match, or of one rubber of a tie."""

    id = serializers.UUIDField()
    version = serializers.IntegerField()
    rubber = serializers.IntegerField(allow_null=True, help_text="The rubber's position; null for the match.")
    winner_id = serializers.UUIDField()
    winner = serializers.CharField()
    outcome = serializers.ChoiceField(choices=Match.Outcome.choices)
    games = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    )
    source = serializers.ChoiceField(choices=OfficialResult.Source.choices)
    reason = serializers.CharField(allow_blank=True, help_text="Why it was corrected.")
    recorded_by = serializers.CharField(allow_blank=True)
    accepted_at = serializers.DateTimeField()
    current = serializers.BooleanField(help_text="The version that stands.")
    struck_out = serializers.BooleanField(help_text="Removed without a replacement: played again.")
    processing = serializers.BooleanField(help_text="What follows from it is still being worked out.")


class ResultEntrySerializer(serializers.Serializer):
    """A result recorded by the organizers. `games` are [a, b] points in playing order: none for a
    walkover, the games played so far for a retirement. For a tie, name the rubber."""

    winner_entry_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=Match.Outcome.choices, default=Match.Outcome.PLAYED)
    games = serializers.ListField(
        child=serializers.ListField(
            child=serializers.IntegerField(min_value=0, max_value=99), min_length=2, max_length=2
        ),
        required=False,
        default=list,
        max_length=9,
    )
    rubber_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(
        max_length=300,
        trim_whitespace=True,
        allow_blank=True,
        required=False,
        default="",
        help_text="Why, kept in the match-day log: for a walkover, a no-show after the grace period, a "
        "withdrawal or an injury before the start (REQ-043).",
    )


class EntryWalkoverSerializer(serializers.Serializer):
    """The referee gives an entry's opponents every match it has left in the event by walkover."""

    reason = serializers.CharField(
        max_length=300,
        trim_whitespace=True,
        allow_blank=True,
        required=False,
        default="",
        help_text="Why, kept in the match-day log for each match: a no-show after the grace period, a "
        "withdrawal or an injury before the start (REQ-043).",
    )


class WalkedOverMatchSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    label = serializers.CharField(help_text='Where it sits in the draw: "Group A", "Knockout round 2".')
    opponent = serializers.CharField(allow_blank=True)
    code = serializers.CharField(allow_blank=True, help_text="Why it was left out; empty when awarded.")
    message = serializers.CharField(allow_blank=True)


class EntryWalkoversSerializer(serializers.Serializer):
    awarded = WalkedOverMatchSerializer(many=True, help_text="Matches the opponent now wins by walkover.")
    skipped = WalkedOverMatchSerializer(
        many=True, help_text="Matches left as they were: play had begun, the opponent isn't known yet, …"
    )


class ResultCorrectionSerializer(ResultEntrySerializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class ResolutionSerializer(serializers.Serializer):
    """A later match that had started with an entry a corrected result says should not be there."""

    id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    match_id = serializers.UUIDField()
    label = serializers.CharField()
    a = serializers.CharField(allow_blank=True)
    b = serializers.CharField(allow_blank=True)
    side = serializers.ChoiceField(choices=["a", "b"])
    old_entry = serializers.CharField(allow_blank=True, help_text="Who is in the match now.")
    new_entry = serializers.CharField(
        allow_blank=True, help_text="Who should be; empty when an earlier match is played again first."
    )
    progress = serializers.ChoiceField(choices=["decided", "on_table", "being_scored", "not_started"])
    reason = serializers.CharField(help_text="The reason given for the correction.")
    corrected_by = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    choice = serializers.ChoiceField(choices=Resolution.Choice.choices, allow_blank=True)
    note = serializers.CharField(allow_blank=True)
    resolved_by = serializers.CharField(allow_blank=True)
    resolved_at = serializers.DateTimeField(allow_null=True)


class ResolveSerializer(serializers.Serializer):
    choice = serializers.ChoiceField(choices=[Resolution.Choice.KEEP, Resolution.Choice.REPLACE])
    note = serializers.CharField(max_length=300, trim_whitespace=True)


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
    result = OfficialResultSerializer(allow_null=True, help_text="The official result that stands.")
    result_history = OfficialResultSerializer(
        many=True, help_text="Every version, of the match and of its rubbers. Competition staff only."
    )
    can_record_result = serializers.BooleanField(help_text="The caller may enter or correct its result.")
    can_award_walkover = serializers.BooleanField(
        help_text="The caller is the referee: they may also award or change a walkover or a disqualification."
    )
    held_for_correction = serializers.BooleanField(
        help_text="A corrected earlier result put its opponent in question; nothing is played until settled."
    )


class DrawGroupSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    name = serializers.CharField()


KEEP_APART_CHOICES = [("clubs", "Clubs"), ("teams", "Teams"), ("regions", "Regions")]


class DrawLimitBreachSerializer(serializers.Serializer):
    """A group over the limit: `count` entries of the club, team or region `name`, `limit` allowed."""

    group = serializers.IntegerField()
    name = serializers.CharField()
    count = serializers.IntegerField()
    limit = serializers.IntegerField()


class DrawMissingEntrySerializer(serializers.Serializer):
    entry = DrawEntrySerializer()
    suggested_group = serializers.IntegerField(
        allow_null=True,
        help_text="The smallest group it can join within the draw's rules; null for a knockout.",
    )


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
    moved_at = serializers.DateTimeField(
        allow_null=True, help_text="When the organizers last moved an entry by hand; null if never."
    )
    keep_apart = serializers.ListField(
        child=serializers.ChoiceField(choices=KEEP_APART_CHOICES),
        help_text="What the organizers chose to keep apart in the groups.",
    )
    same_group_limit = serializers.IntegerField(
        help_text="The most entries of one club, team or region kept apart that a group may hold."
    )
    over_limit = DrawLimitBreachSerializer(
        many=True,
        help_text="In the organizers' preview: groups holding more entries of one club, team or region than "
        "allowed. The draw can't be published while any is listed.",
    )
    not_in_draw = DrawMissingEntrySerializer(
        many=True,
        help_text="In the organizers' preview: accepted entries the draw doesn't hold yet, entered since "
        "it was made, with the group suggested for each.",
    )
    groups = DrawGroupSerializer(many=True)
    places = DrawPlaceSerializer(many=True)
    matches = MatchSerializer(many=True)


class EventDrawSerializer(serializers.Serializer):
    """The event's published draw and, for competition staff only, the preview being worked on."""

    published = DrawSerializer(allow_null=True)
    preview = DrawSerializer(allow_null=True)
    recommended_seeds = serializers.ListField(child=serializers.UUIDField())


class DrawRequestSerializer(serializers.Serializer):
    """Seeds in order, best first (accepted entries of the event). `rng_seed` repeats an earlier draw."""

    seeded_entry_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=MAX_SEEDS, required=False
    )
    rng_seed = serializers.IntegerField(min_value=0, max_value=2**31 - 1, required=False)
    keep_apart = serializers.ListField(
        child=serializers.ChoiceField(choices=KEEP_APART_CHOICES),
        max_length=3,
        required=False,
        help_text="In a groups stage, keep entries of one club, team or region apart. All three when left "
        "out; an empty list keeps nothing apart.",
    )
    same_group_limit = serializers.IntegerField(
        min_value=1,
        max_value=16,
        required=False,
        help_text="The most entries of one of them a group may hold (3 when left out), or its fair share "
        "when it has too many entries for that.",
    )


class DrawMoveSerializer(serializers.Serializer):
    """Change one entry's place in the preview: into a group (`group`: moved there, or added there when it
    is an accepted entry the draw doesn't hold yet), into another entry's place (`swap_with`), or out
    of the draw when it is no longer accepted (`remove`). Exactly one of the three."""

    entry_id = serializers.UUIDField()
    group = serializers.IntegerField(min_value=1, max_value=64, required=False)
    swap_with = serializers.UUIDField(required=False)
    remove = serializers.BooleanField(
        required=False, help_text="Take an entry that is no longer accepted out of its group."
    )

    def validate(self, attrs):
        if attrs.get("remove") is False:
            del attrs["remove"]
        if sum(name in attrs for name in ("group", "swap_with", "remove")) != 1:
            raise serializers.ValidationError(
                "Give one of: a group to move or add it to, an entry to swap with, or remove."
            )
        return attrs


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


class PlayerMatchSerializer(MatchSerializer):
    """One of the player's matches, from the published draw. `side` says which of `a` and `b` is theirs."""

    side = serializers.ChoiceField(choices=[("a", "a"), ("b", "b")])
    result = serializers.ChoiceField(
        choices=[("won", "won"), ("lost", "lost"), ("", "")],
        allow_blank=True,
        help_text="For the player: won or lost; empty while it isn't decided, and for a bye.",
    )


class PlayerEventSerializer(serializers.Serializer):
    """The player's part in one event: their entry, where the published draw put them, and their matches."""

    event = EntryEventSerializer()
    entry = DrawEntrySerializer()
    entry_status = serializers.ChoiceField(choices=Entry.Status.choices, source="entry.status")
    seed = serializers.IntegerField(allow_null=True)
    group_name = serializers.CharField(allow_blank=True, help_text="Empty in a knockout or a single group.")
    group_rank = serializers.IntegerField(allow_null=True, help_text="Their rank in the group (or pool) now.")
    placement = serializers.CharField(
        allow_blank=True, help_text='What the event has decided about them, e.g. "Winner"; empty until then.'
    )
    won = serializers.IntegerField()
    lost = serializers.IntegerField()
    matches = PlayerMatchSerializer(many=True)


class TournamentPlayerSerializer(serializers.Serializer):
    """One player in one tournament: the profile the reader may see, and their record there."""

    player = serializers.SerializerMethodField()
    has_player_page = serializers.BooleanField(
        help_text="The reader may open the player's own page (a listed player, to a signed-in reader)."
    )
    won = serializers.IntegerField()
    lost = serializers.IntegerField()
    events = PlayerEventSerializer(many=True)

    @extend_schema_field(PlayerSerializer)
    def get_player(self, shown) -> dict:
        return shown["player"]
