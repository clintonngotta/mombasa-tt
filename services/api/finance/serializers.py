from datetime import date

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from attachments.serializers import AttachmentLinkSerializer

from . import dues, ledger, welfare
from .models import Campaign, Charge, Expense, Payment, WelfareProject


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


class ContributorSerializer(serializers.Serializer):
    name = serializers.CharField(help_text='"Anonymous" for those who asked')
    amount_minor = serializers.IntegerField()


class WelfareDueTermsSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField()
    due_on = serializers.DateField()


class MyWelfareDueSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField()
    outstanding_minor = serializers.IntegerField()
    due_on = serializers.DateField()
    status = serializers.ChoiceField(choices=["paid", "partial", "pending", "overdue"])


class WelfareVisitSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    place = serializers.CharField()
    status = serializers.ChoiceField(choices=["draft", "published", "cancelled"])
    going = serializers.ListField(child=serializers.CharField(), help_text="Display names")


class WelfareDueSerializer(serializers.Serializer):
    """Make giving required. The amount defaults to the suggested gift, the date to the deadline."""

    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False)
    due_on = serializers.DateField(required=False)


class WelfareProjectSerializer(serializers.ModelSerializer):
    """A welfare project as the viewer may see it: totals for everyone in the audience, their own gift,
    and a contributor list only when the club shows one."""

    title = serializers.CharField(max_length=120, trim_whitespace=True)
    beneficiary_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    beneficiary_name = serializers.SerializerMethodField()
    suggested_minor = serializers.IntegerField(
        min_value=1, max_value=100_000_000, allow_null=True, required=False
    )
    target_minor = serializers.IntegerField(
        min_value=1, max_value=1_000_000_000, allow_null=True, required=False
    )
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    member_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        default=list,
        help_text="The members a selected-audience project is for.",
    )
    hidden = serializers.SerializerMethodField()
    closed = serializers.SerializerMethodField()
    received_minor = serializers.SerializerMethodField()
    spent_minor = serializers.SerializerMethodField()
    remaining_minor = serializers.SerializerMethodField()
    my_contribution_minor = serializers.SerializerMethodField()
    contributors = serializers.SerializerMethodField()
    required = serializers.SerializerMethodField()
    due = serializers.SerializerMethodField()
    expected_minor = serializers.SerializerMethodField()
    my_due = serializers.SerializerMethodField()
    visits = serializers.SerializerMethodField()

    class Meta:
        model = WelfareProject
        fields = [
            "id",
            "title",
            "description",
            "beneficiary_id",
            "beneficiary_name",
            "suggested_minor",
            "currency",
            "target_minor",
            "deadline",
            "audience",
            "member_ids",
            "show_contributors",
            "hidden",
            "closed",
            "received_minor",
            "spent_minor",
            "remaining_minor",
            "my_contribution_minor",
            "contributors",
            "required",
            "due",
            "expected_minor",
            "my_due",
            "visits",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def _today(self):
        return self.context.get("today") or timezone.localdate()

    def _totals(self, project):
        cache = self.context.setdefault("totals", {})
        if project.pk not in cache:
            cache[project.pk] = welfare.totals(project)
        return cache[project.pk]

    def get_beneficiary_name(self, project) -> str | None:
        return project.beneficiary.display_name if project.beneficiary_id else None

    def get_hidden(self, project) -> bool:
        return project.hidden_at is not None

    def get_closed(self, project) -> bool:
        return welfare.is_closed(project, self._today())

    def get_received_minor(self, project) -> int:
        return self._totals(project)["received_minor"]

    def get_spent_minor(self, project) -> int:
        return self._totals(project)["spent_minor"]

    def get_remaining_minor(self, project) -> int:
        return self._totals(project)["remaining_minor"]

    def get_my_contribution_minor(self, project) -> int:
        user = self.context.get("user")
        return welfare.own_total(project, user) if user else 0

    @extend_schema_field(ContributorSerializer(many=True, allow_null=True))
    def get_contributors(self, project):
        if not project.show_contributors:
            return None
        return ContributorSerializer(welfare.contributor_list(project), many=True).data

    def get_required(self, project) -> bool:
        """Made a due (REQ-023): only then does anyone owe, or show as overdue."""
        return project.campaign_id is not None

    @extend_schema_field(WelfareDueTermsSerializer(allow_null=True))
    def get_due(self, project):
        if not project.campaign_id:
            return None
        return {"amount_minor": project.campaign.amount_minor, "due_on": project.campaign.starts_on}

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_expected_minor(self, project):
        """Dues not paid yet, for welfare and finance staff; null for everyone else."""
        return welfare.expected_total(project) if self.context.get("staff") else None

    @extend_schema_field(MyWelfareDueSerializer(allow_null=True))
    def get_my_due(self, project):
        return welfare.own_due(project, self.context.get("user"), self._today())

    @extend_schema_field(WelfareVisitSerializer(many=True))
    def get_visits(self, project):
        user = self.context.get("user")
        if user is None:
            return []
        return WelfareVisitSerializer(welfare.visits(project, user), many=True).data


class WelfareUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, trim_whitespace=True, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    suggested_minor = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    target_minor = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    deadline = serializers.DateField(allow_null=True, required=False)
    show_contributors = serializers.BooleanField(required=False)


class WelfareContributionSerializer(serializers.Serializer):
    """A gift as finance and welfare staff see it."""

    id = serializers.UUIDField(read_only=True)
    contributor_id = serializers.UUIDField()
    contributor_name = serializers.CharField(read_only=True)
    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    received_on = serializers.DateField()
    request_key = serializers.UUIDField(write_only=True)
    anonymous = serializers.BooleanField(default=False)
    reversed = serializers.BooleanField(read_only=True)

    def to_representation(self, contribution):
        payment = contribution.payment
        return {
            "id": str(contribution.id),
            "contributor_id": str(contribution.contributor_id),
            "contributor_name": contribution.contributor.display_name,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "method": payment.method,
            "reference": payment.reference,
            "received_on": payment.received_on.isoformat(),
            "anonymous": contribution.anonymous,
            "reversed": payment.reversed_at is not None,
        }
