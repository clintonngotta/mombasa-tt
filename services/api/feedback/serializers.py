from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import service
from .models import FeedbackForm

ITEM_ID = r"^[0-9a-f]{12}$"
KIND_CHOICES = [(kind, kind) for kind in service.KINDS]


class Strict(serializers.Serializer):
    """Refuses fields it doesn't know."""

    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", None) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class FeedbackChoiceSerializer(serializers.Serializer):
    id = serializers.RegexField(ITEM_ID, required=False)
    text = serializers.CharField(max_length=120, trim_whitespace=True)


class FeedbackQuestionSerializer(serializers.Serializer):
    id = serializers.RegexField(
        ITEM_ID, required=False, help_text="Given by the API; send it back to keep the question."
    )
    kind = serializers.ChoiceField(choices=KIND_CHOICES)
    text = serializers.CharField(max_length=300, trim_whitespace=True)
    help = serializers.CharField(
        max_length=300, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    required = serializers.BooleanField(required=False, default=False)
    choices = FeedbackChoiceSerializer(many=True, required=False, max_length=service.MAX_CHOICES)

    def validate(self, attrs):
        choices = attrs.get("choices") or []
        if attrs["kind"] in service.CHOICE_KINDS:
            if len(choices) < 2:
                raise serializers.ValidationError({"choices": "Give at least two choices."})
            texts = [choice["text"].lower() for choice in choices]
            if len(set(texts)) != len(texts):
                raise serializers.ValidationError({"choices": "Each choice is listed once."})
        return attrs


class FeedbackSectionSerializer(serializers.Serializer):
    id = serializers.RegexField(ITEM_ID, required=False)
    title = serializers.CharField(
        max_length=120, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    description = serializers.CharField(
        max_length=500, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    questions = FeedbackQuestionSerializer(many=True, required=False, max_length=service.MAX_QUESTIONS)


class FeedbackGuestSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class FeedbackTournamentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class FeedbackFormSerializer(serializers.ModelSerializer):
    """A form as its host's competition staff see it."""

    title = serializers.CharField(max_length=120, trim_whitespace=True)
    intro = serializers.CharField(max_length=1000, trim_whitespace=True, allow_blank=True, required=False)
    sections = FeedbackSectionSerializer(many=True, required=False, max_length=service.MAX_SECTIONS)
    tournament = FeedbackTournamentSerializer(read_only=True, allow_null=True)
    tournament_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    guests = FeedbackGuestSerializer(many=True, read_only=True)
    guest_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        max_length=200,
        help_text="Named guests: members of the host or players listed in the directory.",
    )
    copy_from = serializers.UUIDField(
        write_only=True,
        required=False,
        help_text="Start from the sections of another form or template of this organization.",
    )
    open = serializers.SerializerMethodField(help_text="Sent, and between its opening and closing times.")
    recipients = serializers.IntegerField(source="recipient_count", read_only=True, default=0)
    responses = serializers.IntegerField(source="response_count", read_only=True, default=0)

    class Meta:
        model = FeedbackForm
        fields = [
            "id",
            "title",
            "intro",
            "is_template",
            "tournament",
            "tournament_id",
            "sections",
            "anonymous",
            "to_entrants",
            "to_umpires",
            "to_staff",
            "guests",
            "guest_ids",
            "copy_from",
            "status",
            "opens_at",
            "closes_at",
            "sent_at",
            "open",
            "recipients",
            "responses",
            "created_at",
        ]
        read_only_fields = ["id", "status", "opens_at", "closes_at", "sent_at", "created_at"]

    def get_open(self, form) -> bool:
        return service.is_open(form)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        if "sections" in attrs:
            count = sum(len(section.get("questions", [])) for section in attrs["sections"])
            if count > service.MAX_QUESTIONS:
                raise serializers.ValidationError(
                    {"sections": f"Keep a form to {service.MAX_QUESTIONS} questions."}
                )
            attrs["sections"] = service.stored_sections(attrs["sections"])
        return attrs


class SendFeedbackFormSerializer(Strict):
    opens_at = serializers.DateTimeField(required=False, help_text="Defaults to now.")
    closes_at = serializers.DateTimeField()


class FeedbackClosingSerializer(Strict):
    closes_at = serializers.DateTimeField(help_text="A later time to keep it open, or now to close it.")


class FeedbackCountSerializer(serializers.Serializer):
    label = serializers.CharField()
    count = serializers.IntegerField()


class QuestionTotalsSerializer(serializers.Serializer):
    id = serializers.CharField()
    section = serializers.CharField(allow_blank=True)
    kind = serializers.ChoiceField(choices=KIND_CHOICES)
    text = serializers.CharField()
    answered = serializers.IntegerField()
    average = serializers.FloatField(allow_null=True)
    counts = FeedbackCountSerializer(many=True)
    texts = serializers.ListField(child=serializers.CharField())


class FeedbackTotalsSerializer(serializers.Serializer):
    responses = serializers.IntegerField()
    recipients = serializers.IntegerField()
    questions = QuestionTotalsSerializer(many=True)


class FeedbackHostSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MyFeedbackFormSerializer(serializers.ModelSerializer):
    """A form as someone asked to answer it sees it, with their own answers."""

    organization = FeedbackHostSerializer(read_only=True)
    tournament = FeedbackTournamentSerializer(read_only=True, allow_null=True)
    sections = FeedbackSectionSerializer(many=True, read_only=True)
    open = serializers.SerializerMethodField()
    answered = serializers.SerializerMethodField()
    my_answers = serializers.SerializerMethodField(
        help_text="Your answers by question id: a number, true or false, text, a choice id or a list of them."
    )

    class Meta:
        model = FeedbackForm
        fields = [
            "id",
            "organization",
            "tournament",
            "title",
            "intro",
            "sections",
            "anonymous",
            "opens_at",
            "closes_at",
            "open",
            "answered",
            "my_answers",
        ]
        read_only_fields = fields

    def get_open(self, form) -> bool:
        return service.is_open(form)

    def get_answered(self, form) -> bool:
        return form.pk in self.context.get("answered", ())

    @extend_schema_field(serializers.DictField())
    def get_my_answers(self, form) -> dict:
        return self.context.get("answers", {}).get(form.pk, {})


class FeedbackAnswersSerializer(Strict):
    answers = serializers.DictField()
