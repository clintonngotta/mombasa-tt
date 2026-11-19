from rest_framework import serializers

from competitions.streams import checked_url, domain_of

from .models import CATEGORIES, ExternalEvent, LinkReport


class ListedEventSerializer(serializers.Serializer):
    """One entry of the public listing: a Coast TT tournament or an external event."""

    kind = serializers.ChoiceField(choices=["coast", "external"])
    id = serializers.UUIDField()
    name = serializers.CharField()
    organizer = serializers.CharField()
    host_id = serializers.UUIDField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    timezone = serializers.CharField()
    venue = serializers.CharField()
    town = serializers.CharField()
    categories = serializers.ListField(child=serializers.CharField())
    status = serializers.ChoiceField(choices=["scheduled", "postponed", "cancelled", "completed"])
    review = serializers.CharField(
        allow_null=True, help_text="External events: pending shows as awaiting review."
    )
    live = serializers.BooleanField()
    info_url = serializers.CharField()
    info_domain = serializers.CharField()
    live_url = serializers.CharField(
        help_text="External events while live; a Coast TT event links to its page."
    )
    live_domain = serializers.CharField()
    entry_info = serializers.CharField()


def _https(value):
    if not value:
        return ""
    url, _ = checked_url(value)
    return url


class ExternalEventSerializer(serializers.ModelSerializer):
    """An external event as its submitting club's staff and the curators see it."""

    name = serializers.CharField(max_length=120, trim_whitespace=True)
    organizer = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)
    venue = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    categories = serializers.ListField(
        child=serializers.ChoiceField(choices=CATEGORIES), required=False, max_length=8
    )
    info_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    live_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    submitted_by_club = serializers.CharField(source="submitted_by_org.name", read_only=True)
    live_domain = serializers.SerializerMethodField()
    report_count = serializers.SerializerMethodField()

    class Meta:
        model = ExternalEvent
        fields = [
            "id",
            "name",
            "organizer",
            "starts_on",
            "ends_on",
            "timezone",
            "venue",
            "town",
            "country",
            "categories",
            "entry_info",
            "info_url",
            "live_url",
            "live_domain",
            "marked_live",
            "status",
            "review",
            "review_note",
            "submitted_by_club",
            "report_count",
            "created_at",
        ]
        read_only_fields = ["id", "marked_live", "review", "review_note", "submitted_by_club", "created_at"]

    def validate_info_url(self, value):
        return _https(value)

    def validate_live_url(self, value):
        return _https(value)

    def validate_timezone(self, value):
        from zoneinfo import available_timezones

        if value not in available_timezones():
            raise serializers.ValidationError("Choose a timezone.")
        return value

    def validate(self, attrs):
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "It ends on or after its first day."})
        if "categories" in attrs:
            attrs["categories"] = list(dict.fromkeys(attrs["categories"]))
        return attrs

    def get_live_domain(self, event) -> str:
        return domain_of(event.live_url) if event.live_url else ""

    def get_report_count(self, event) -> int:
        return event.link_reports.count()


class ReviewSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, trim_whitespace=True)


class MarkLiveSerializer(serializers.Serializer):
    live = serializers.BooleanField()


class LinkReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = LinkReport
        fields = ["reason"]
