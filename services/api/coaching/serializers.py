from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from competitions.official import title
from core.timezones import validate_timezone
from matchlog.models import PersonalMatch
from organizations.models import Membership
from training.models import Skill
from training.serializers import TrainingPlanSerializer

from .models import Availability, Booking, Coaching, CoachProfile, Level, MatchComment


class PersonRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class ClubRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    town = serializers.CharField()


class AvailabilitySerializer(serializers.ModelSerializer):
    venue = serializers.CharField(max_length=120, allow_blank=True, required=False, trim_whitespace=True)

    class Meta:
        model = Availability
        fields = ["weekday", "starts", "ends", "venue"]

    def validate_weekday(self, value):
        if value > 6:
            raise serializers.ValidationError("Choose a day of the week.")
        return value

    def validate(self, attrs):
        if attrs["ends"] <= attrs["starts"]:
            raise serializers.ValidationError({"ends": "The window ends before it starts."})
        return attrs


class AvailabilityListSerializer(serializers.Serializer):
    windows = AvailabilitySerializer(many=True)

    def validate_windows(self, windows):
        if len(windows) > 42:
            raise serializers.ValidationError("Enter at most 42 windows.")
        by_day: dict[int, list] = {}
        for window in windows:
            by_day.setdefault(window["weekday"], []).append(window)
        for day in by_day.values():
            day.sort(key=lambda w: w["starts"])
            for before, after in zip(day, day[1:], strict=False):
                if after["starts"] < before["ends"]:
                    raise serializers.ValidationError("Two windows on the same day overlap.")
        return windows


class CoachProfileSerializer(serializers.ModelSerializer):
    """A coach as players see them. `organizations` are the clubs where they coach."""

    user = PersonRefSerializer(read_only=True)
    headline = serializers.CharField(max_length=120, trim_whitespace=True)
    bio = serializers.CharField(max_length=2000, allow_blank=True, required=False, trim_whitespace=True)
    levels = serializers.ListField(child=serializers.ChoiceField(Level.choices), required=False, max_length=3)
    specialties = serializers.ListField(
        child=serializers.ChoiceField(Skill.choices), required=False, max_length=len(Skill.choices)
    )
    organizations = ClubRefSerializer(many=True, read_only=True)
    organization_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False, max_length=10
    )
    availability = serializers.SerializerMethodField()

    class Meta:
        model = CoachProfile
        fields = [
            "id",
            "user",
            "headline",
            "bio",
            "levels",
            "specialties",
            "rate_minor",
            "currency",
            "region",
            "town",
            "timezone",
            "organizations",
            "organization_ids",
            "accepting",
            "availability",
        ]
        read_only_fields = ["id", "user", "organizations", "availability"]

    @extend_schema_field(AvailabilitySerializer(many=True))
    def get_availability(self, profile) -> list[dict]:
        return AvailabilitySerializer(profile.user.coach_availability.all(), many=True).data

    def validate_timezone(self, value):
        return validate_timezone(value)

    def validate_levels(self, value):
        return list(dict.fromkeys(value))

    def validate_specialties(self, value):
        return list(dict.fromkeys(value))

    def validate_organization_ids(self, value):
        """Only clubs the coach is an active member of."""
        user = self.context["request"].user
        wanted = set(value)
        clubs = set(
            Membership.objects.active()
            .filter(user=user, organization__in=wanted)
            .values_list("organization", flat=True)
        )
        if wanted - clubs:
            raise serializers.ValidationError("Choose clubs you are a member of.")
        return list(wanted)

    def save(self, **kwargs):
        organization_ids = self.validated_data.pop("organization_ids", None)
        profile = super().save(**kwargs)
        if organization_ids is not None:
            profile.organizations.set(organization_ids)
        return profile


class CoachingSerializer(serializers.ModelSerializer):
    """A coaching from the caller's side: `role` is "coach" when they coach the other person."""

    coach = PersonRefSerializer(read_only=True)
    trainee = PersonRefSerializer(read_only=True)
    role = serializers.SerializerMethodField()
    awaiting_me = serializers.SerializerMethodField()

    class Meta:
        model = Coaching
        fields = [
            "id",
            "coach",
            "trainee",
            "role",
            "status",
            "awaiting_me",
            "message",
            "created_at",
            "started_at",
            "ended_at",
        ]
        read_only_fields = fields

    def get_role(self, coaching) -> str:
        return "coach" if coaching.coach_id == self.context["request"].user.pk else "trainee"

    def get_awaiting_me(self, coaching) -> bool:
        me = self.context["request"].user.pk
        return coaching.status == Coaching.Status.REQUESTED and coaching.requested_by_id != me


class CoachingRequestSerializer(serializers.Serializer):
    """Ask a coach to coach you (`coach_id`), or, as a coach, invite a player (`trainee_id`)."""

    coach_id = serializers.UUIDField(required=False)
    trainee_id = serializers.UUIDField(required=False)
    message = serializers.CharField(max_length=300, allow_blank=True, required=False, trim_whitespace=True)

    def validate(self, attrs):
        if bool(attrs.get("coach_id")) == bool(attrs.get("trainee_id")):
            raise serializers.ValidationError("Choose a coach to ask, or a player to invite.")
        return attrs


class BookingSerializer(serializers.ModelSerializer):
    coach = PersonRefSerializer(read_only=True)
    trainee = PersonRefSerializer(read_only=True)
    role = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "coach",
            "trainee",
            "role",
            "starts_at",
            "ends_at",
            "venue",
            "note",
            "status",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_role(self, booking) -> str:
        return "coach" if booking.coach_id == self.context["request"].user.pk else "trainee"


class BookingRequestSerializer(serializers.Serializer):
    coach_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    venue = serializers.CharField(max_length=120, allow_blank=True, required=False, trim_whitespace=True)
    note = serializers.CharField(max_length=300, allow_blank=True, required=False, trim_whitespace=True)

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": "The session ends before it starts."})
        return attrs


class BookingReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, allow_blank=True, required=False, trim_whitespace=True)


class SlotSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    venue = serializers.CharField()


class CommentSerializer(serializers.ModelSerializer):
    coach = PersonRefSerializer(read_only=True)
    body = serializers.CharField(max_length=2000, trim_whitespace=True)

    class Meta:
        model = MatchComment
        fields = ["id", "coach", "personal_match", "match", "body", "created_at", "updated_at"]
        read_only_fields = ["id", "coach", "personal_match", "match", "created_at", "updated_at"]


class CommentInputSerializer(serializers.Serializer):
    personal_match = serializers.UUIDField(required=False)
    match = serializers.UUIDField(required=False)
    body = serializers.CharField(max_length=2000, trim_whitespace=True)

    def validate(self, attrs):
        if bool(attrs.get("personal_match")) == bool(attrs.get("match")):
            raise serializers.ValidationError("Choose one match to comment on.")
        return attrs


class AssignPlanSerializer(serializers.Serializer):
    """Give the trainee a copy of one of your plans or of a club plan you can read, or a new empty plan."""

    source_plan_id = serializers.UUIDField(required=False)
    title = serializers.CharField(max_length=80, required=False, trim_whitespace=True)

    def validate(self, attrs):
        if not attrs.get("source_plan_id") and not attrs.get("title"):
            raise serializers.ValidationError({"title": "Give the plan a title or choose one to copy."})
        return attrs


class TraineeMatchSerializer(serializers.Serializer):
    """One of the trainee's matches as their coach sees it, with the coach's comments on it."""

    kind = serializers.ChoiceField(["personal", "official"])
    id = serializers.UUIDField()
    played_on = serializers.DateField(allow_null=True)
    title = serializers.CharField()
    opponent = serializers.CharField()
    result = serializers.CharField(allow_blank=True)
    score = serializers.CharField(allow_blank=True)
    comments = CommentSerializer(many=True)


class TraineeRatingSerializer(serializers.Serializer):
    discipline = serializers.CharField()
    rating = serializers.FloatField()
    played = serializers.IntegerField()
    won = serializers.IntegerField()


class TraineeSerializer(serializers.Serializer):
    """What a coach sees of a trainee: the plans they gave them with progress, recent matches, ratings
    and sessions booked between them."""

    coaching = CoachingSerializer()
    plans = TrainingPlanSerializer(many=True)
    matches = TraineeMatchSerializer(many=True)
    ratings = TraineeRatingSerializer(many=True)
    bookings = BookingSerializer(many=True)
    record = serializers.DictField(child=serializers.IntegerField())


class CalendarEntrySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(["booking", "session", "trainee_session", "club_session", "tournament"])
    id = serializers.UUIDField()
    title = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    starts_at = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    starts_on = serializers.DateField(allow_null=True)
    ends_on = serializers.DateField(allow_null=True)
    status = serializers.CharField(allow_blank=True)
    link = serializers.CharField(allow_blank=True)


def personal_row(match: PersonalMatch, comments) -> dict:
    won, lost = match.tally()
    return {
        "kind": "personal",
        "id": match.id,
        "played_on": match.played_on,
        "title": match.label,
        "opponent": match.opponent_name,
        "result": match.result if (won or lost) else "",
        "score": f"{won}–{lost}" if (won or lost) else "",
        "comments": comments,
    }


def official_row(match, user, comments) -> dict:
    mine = None
    for entry in (match.entry_a, match.entry_b):
        if entry and any(p.user_id == user.pk for p in entry.players.all()):
            mine = entry
    other = match.entry_b if mine is not None and mine == match.entry_a else match.entry_a
    event = match.draw.event
    won = sum(1 for a, b in match.games if (a > b) == (mine == match.entry_a))
    result = ""
    if match.status == "completed" and mine is not None:
        result = "win" if match.winner_id == mine.pk else "loss"
    return {
        "kind": "official",
        "id": match.id,
        "played_on": (match.scheduled_at.date() if match.scheduled_at else event.tournament.starts_on),
        "title": f"{event.tournament.name}: {event.name}",
        "opponent": title(other),
        "result": result,
        "score": f"{won}–{len(match.games) - won}" if match.games else "",
        "comments": comments,
    }
