from datetime import date

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from attachments.serializers import AttachmentLinkSerializer

from . import dues, ledger
from .models import Campaign, Charge, Expense, Payment


class ChargeSerializer(serializers.ModelSerializer):
    member_id = serializers.UUIDField(allow_null=True, help_text="None for a facility walk-in")
    member_name = serializers.SerializerMethodField()
    purpose = serializers.CharField(max_length=120, trim_whitespace=True)
    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    paid_minor = serializers.SerializerMethodField()
    outstanding_minor = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    campaign_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Charge
        fields = [
            "id",
            "member_id",
            "member_name",
            "kind",
            "campaign_id",
            "period",
            "purpose",
            "amount_minor",
            "currency",
            "due_on",
            "paid_minor",
            "outstanding_minor",
            "status",
            "waive_reason",
            "created_at",
        ]
        read_only_fields = ["id", "period", "waive_reason", "created_at"]

    def get_member_name(self, charge) -> str:
        return charge.member.display_name if charge.member_id else f"{charge.walk_in_name} (walk-in)"

    def get_paid_minor(self, charge) -> int:
        return ledger.paid_towards(charge)

    def get_outstanding_minor(self, charge) -> int:
        return ledger.outstanding(charge)

    def get_status(self, charge) -> str:
        return ledger.status(charge, self.context.get("today") or timezone.localdate())


class PaymentSerializer(serializers.ModelSerializer):
    payer_id = serializers.UUIDField(allow_null=True, help_text="None for a facility walk-in")
    payer_name = serializers.SerializerMethodField()
    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    reference = serializers.CharField(
        max_length=60, required=False, allow_blank=True, trim_whitespace=True, default=""
    )
    request_key = serializers.UUIDField(
        write_only=True, help_text="A new id per payment recorded; sending it again records nothing new."
    )
    allocated_minor = serializers.SerializerMethodField()
    credit_minor = serializers.SerializerMethodField()
    reversed = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "payer_id",
            "payer_name",
            "amount_minor",
            "currency",
            "method",
            "reference",
            "received_on",
            "request_key",
            "allocated_minor",
            "credit_minor",
            "reversed",
            "reversal_reason",
            "created_at",
        ]
        read_only_fields = ["id", "reversal_reason", "created_at"]

    def get_payer_name(self, payment) -> str:
        return payment.payer.display_name if payment.payer_id else f"{payment.walk_in_name} (walk-in)"

    def get_allocated_minor(self, payment) -> int:
        return 0 if payment.reversed_at else ledger.allocated_from(payment)

    def get_credit_minor(self, payment) -> int:
        return ledger.credit(payment)

    def get_reversed(self, payment) -> bool:
        return payment.reversed_at is not None


class AllocateSerializer(serializers.Serializer):
    charge_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)


class FinanceReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class BalanceSerializer(serializers.Serializer):
    member_id = serializers.UUIDField()
    member_name = serializers.CharField()
    currency = serializers.CharField()
    owed_minor = serializers.IntegerField()
    credit_minor = serializers.IntegerField()


class MyDueSummarySerializer(serializers.Serializer):
    """One campaign as the member sees it: their own dues only."""

    campaign_id = serializers.UUIDField()
    title = serializers.CharField()
    cadence = serializers.CharField()
    currency = serializers.CharField()
    outstanding_minor = serializers.IntegerField()
    overdue_minor = serializers.IntegerField()
    next_due_on = serializers.DateField(allow_null=True)


class MyFinancesSerializer(serializers.Serializer):
    charges = ChargeSerializer(many=True)
    payments = PaymentSerializer(many=True)
    balances = BalanceSerializer(many=True)
    dues = MyDueSummarySerializer(many=True)


class CampaignDuesSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField(), help_text="Dues per status.")
    outstanding_minor = serializers.IntegerField()
    overdue_minor = serializers.IntegerField()
    dues = ChargeSerializer(many=True)


class RemindedSerializer(serializers.Serializer):
    sent = serializers.IntegerField()


class CampaignTermSerializer(serializers.Serializer):
    member_id = serializers.UUIDField()
    member_name = serializers.CharField(read_only=True)
    included = serializers.BooleanField(default=True)
    amount_minor = serializers.IntegerField(min_value=0, max_value=100_000_000, allow_null=True, default=None)
    waived = serializers.BooleanField(default=False)
    waive_reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["waived"] and not attrs["waive_reason"].strip():
            raise serializers.ValidationError({"waive_reason": "Give a reason for the waiver."})
        return attrs


class CampaignSerializer(serializers.ModelSerializer):
    title = serializers.CharField(max_length=120, trim_whitespace=True)
    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    member_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        default=list,
        help_text="The members a selected-audience campaign bills.",
    )
    terms = serializers.SerializerMethodField()
    closed = serializers.SerializerMethodField()
    next_due_on = serializers.SerializerMethodField()
    dues_count = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = [
            "id",
            "title",
            "description",
            "amount_minor",
            "currency",
            "cadence",
            "starts_on",
            "ends_on",
            "audience",
            "member_ids",
            "terms",
            "closed",
            "next_due_on",
            "dues_count",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "The last date can't be before the first."})
        return attrs

    @extend_schema_field(CampaignTermSerializer(many=True))
    def get_terms(self, campaign):
        return CampaignTermSerializer(
            [
                {
                    "member_id": t.member_id,
                    "member_name": t.member.display_name,
                    "included": t.included,
                    "amount_minor": t.amount_minor,
                    "waived": t.waived,
                    "waive_reason": t.waive_reason,
                }
                for t in campaign.terms.all()
            ],
            many=True,
        ).data

    def get_closed(self, campaign) -> bool:
        return campaign.closed_at is not None

    def get_next_due_on(self, campaign) -> date | None:
        return dues.next_period(campaign, self.context.get("today") or timezone.localdate())

    def get_dues_count(self, campaign) -> int:
        return campaign.dues.count()


class CampaignUpdateSerializer(serializers.Serializer):
    """What can change once a campaign runs: the cadence and start stay as they were."""

    title = serializers.CharField(max_length=120, trim_whitespace=True, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False)
    ends_on = serializers.DateField(required=False, allow_null=True)


class ExpenseSerializer(serializers.ModelSerializer):
    """An expense as finance staff see it, with a short-lived link to its receipt."""

    campaign_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    campaign_title = serializers.CharField(source="campaign.title", read_only=True, default=None)
    description = serializers.CharField(max_length=200, trim_whitespace=True)
    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    reversed = serializers.SerializerMethodField()
    receipt = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id",
            "campaign_id",
            "campaign_title",
            "description",
            "amount_minor",
            "currency",
            "spent_on",
            "receipt",
            "reversed",
            "reversal_reason",
            "created_at",
        ]
        read_only_fields = ["id", "reversal_reason", "created_at"]

    def get_reversed(self, expense) -> bool:
        return expense.reversed_at is not None

    @extend_schema_field(AttachmentLinkSerializer(allow_null=True))
    def get_receipt(self, expense):
        return AttachmentLinkSerializer(expense.receipt_id).data if expense.receipt_id else None


class ReceiptUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="A photo of the receipt: JPEG, PNG or WebP, up to 5 MB")


class PurposeTotalSerializer(serializers.Serializer):
    campaign_id = serializers.UUIDField(allow_null=True, help_text="None for general running costs")
    title = serializers.CharField()
    currency = serializers.CharField()
    received_minor = serializers.IntegerField(help_text="Actually received: standing matched payments")
    spent_minor = serializers.IntegerField()
    remaining_minor = serializers.IntegerField(help_text="Received less spent; negative is a deficit")
    expected_minor = serializers.IntegerField(help_text="Dues still owed: not received, shown apart")


class SpendingSerializer(serializers.Serializer):
    """What a purpose's money paid for, as members see it: no receipts, no names."""

    campaign_id = serializers.UUIDField(allow_null=True)
    description = serializers.CharField()
    amount_minor = serializers.IntegerField()
    currency = serializers.CharField()
    spent_on = serializers.DateField()


class PurposesSerializer(serializers.Serializer):
    purposes = PurposeTotalSerializer(many=True)
    spending = SpendingSerializer(many=True)
