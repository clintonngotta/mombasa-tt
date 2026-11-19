from django.utils import timezone
from rest_framework import serializers

from . import ledger
from .models import Charge, Payment


class ChargeSerializer(serializers.ModelSerializer):
    member_id = serializers.UUIDField()
    member_name = serializers.CharField(source="member.display_name", read_only=True)
    purpose = serializers.CharField(max_length=120, trim_whitespace=True)
    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    paid_minor = serializers.SerializerMethodField()
    outstanding_minor = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Charge
        fields = [
            "id",
            "member_id",
            "member_name",
            "kind",
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
        read_only_fields = ["id", "waive_reason", "created_at"]

    def get_paid_minor(self, charge) -> int:
        return ledger.paid_towards(charge)

    def get_outstanding_minor(self, charge) -> int:
        return ledger.outstanding(charge)

    def get_status(self, charge) -> str:
        return ledger.status(charge, self.context.get("today") or timezone.localdate())


class PaymentSerializer(serializers.ModelSerializer):
    payer_id = serializers.UUIDField()
    payer_name = serializers.CharField(source="payer.display_name", read_only=True)
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


class MyFinancesSerializer(serializers.Serializer):
    charges = ChargeSerializer(many=True)
    payments = PaymentSerializer(many=True)
    balances = BalanceSerializer(many=True)
