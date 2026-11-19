"""Committees (REQ-045, TASK-106): configurable positions, their holders, custom fields and history.

Holders of governance.manage (the admin, or anyone the admin delegates it to) set the committee. Each
position is held by at most one active member; holding it may grant a role, which counts towards the
holder's permissions only while they hold it (`access.position_roles`). Nobody can attach, give or take
away a role carrying permissions they don't hold themselves, and Admin and Member can't be granted this
way. Every change locks the organization, like role changes do, because it changes who holds what.

Members see the current committee and its history, by display name only; which role a position grants
and staff-only fields are for governance staff. When a holder leaves the organization their time in the
position ends; past holders are never deleted.
"""

from datetime import date
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Max, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term

from .access import (
    effective_permissions,
    lock_organization,
    require_membership,
    require_permission,
    require_within_authority,
)
from .member_fields import clean_value
from .models import (
    CommitteeField,
    CommitteeFieldValue,
    CommitteePosition,
    MemberField,
    Membership,
    Organization,
    PositionHolder,
    Role,
)
from .permissions import Permission
from .serializers import FieldValueField, MemberFieldSerializer, MemberFieldValuesSerializer

GOVERNANCE = Permission.GOVERNANCE_MANAGE
MAX_POSITIONS = 30
MAX_FIELDS = 30
EndReason = PositionHolder.EndReason


def local_today(organization: Organization) -> date:
    return timezone.localdate(timezone=ZoneInfo(organization.timezone))


def is_governance_staff(user, organization: Organization) -> bool:
    return GOVERNANCE in effective_permissions(user, organization)


def active_positions(organization: Organization):
    return organization.committee_positions.filter(retired_at__isnull=True)


def active_fields(organization: Organization, *, staff: bool):
    fields = organization.committee_fields.filter(retired_at__isnull=True)
    return fields if staff else fields.filter(visibility=MemberField.Visibility.MEMBER)


def current_holding(position: CommitteePosition) -> PositionHolder | None:
    return position.holders.select_for_update().filter(ended_at__isnull=True).first()


def _end(holding: PositionHolder, reason: str, today: date) -> None:
    holding.ended_at = timezone.now()
    holding.ended_on = max(today, holding.started_on)
    holding.end_reason = reason
    holding.save(update_fields=["ended_at", "ended_on", "end_reason"])


def end_holdings_on_leaving(membership: Membership) -> None:
    """A member who leaves no longer sits on the committee. Call with the organization locked."""
    today = local_today(membership.organization)
    for holding in membership.committee_holdings.select_for_update().filter(ended_at__isnull=True):
        _end(holding, EndReason.LEFT, today)


def _grantable(organization: Organization, role_id) -> Role | None:
    if role_id is None:
        return None
    role = organization.roles.filter(pk=role_id).first()
    if role is None:
        raise ValidationError({"grants_role": "Choose a role of this organization."})
    if role.is_admin or role.is_member:
        raise ValidationError(
            {"grants_role": f"A position can't grant the {role.name} role. Choose another role."}
        )
    return role


def _guard_role(granted: frozenset[str], role: Role | None) -> None:
    """Giving, moving or removing a role through a position is granting it: stay within your own."""
    if role is not None:
        require_within_authority(granted, role.permission_set)


def assign(organization, granted, actor, position: CommitteePosition, membership_id, started_on):
    """Put an active member in the position, ending the current holder's time (replaced)."""
    membership = (
        Membership.objects.active()
        .filter(organization=organization, pk=membership_id, user__is_active=True)
        .first()
    )
    if membership is None:
        raise ApiException("not_a_member", "Choose an active member of this organization.", 400)
    _guard_role(granted, position.grants_role)
    today = local_today(organization)
    current = current_holding(position)
    if current is not None:
        if current.membership_id == membership.pk:
            raise ApiException("already_holds", "That member already holds this position.", 409)
        _end(current, EndReason.REPLACED, today)
    PositionHolder.objects.create(
        position=position, membership=membership, started_on=started_on or today, assigned_by=actor
    )


def write_values(organization, position: CommitteePosition, staff: bool, submitted: dict, actor) -> None:
    """Apply {field id: value}: position fields to the position, holder fields to its current holder.
    Unknown, retired or hidden field ids are refused together; nothing is saved unless all are valid."""
    fields = {str(field.id): field for field in active_fields(organization, staff=staff)}
    if set(submitted) - set(fields):
        raise ValidationError({"values": "One or more fields don't exist here."})
    holding = current_holding(position)
    cleaned, errors = {}, {}
    for field_id, raw in submitted.items():
        field = fields[field_id]
        if field.applies_to == CommitteeField.AppliesTo.HOLDER and holding is None:
            errors[field_id] = "Nobody holds this position. Assign a holder first."
            continue
        try:
            cleaned[field_id] = clean_value(field, raw)
        except ValueError as error:
            errors[field_id] = str(error)
    if errors:
        raise ValidationError(errors)
    for field_id, value in cleaned.items():
        field = fields[field_id]
        owner = (
            {"holder": holding}
            if field.applies_to == CommitteeField.AppliesTo.HOLDER
            else {"position": position}
        )
        if value is None:
            CommitteeFieldValue.objects.filter(field=field, **owner).delete()
        else:
            CommitteeFieldValue.objects.update_or_create(
                field=field, **owner, defaults={"value": value, "updated_by": actor}
            )


# --- Serializers ---------------------------------------------------------------------------------------


class CommitteeFieldSerializer(MemberFieldSerializer):
    """A committee field definition. `applies_to` and the type are fixed once created."""

    class Meta(MemberFieldSerializer.Meta):
        model = CommitteeField
        fields = ["id", "label", "kind", "options", "required", "visibility", "applies_to", "retired_at"]
        read_only_fields = ["id", "retired_at"]

    def validate_applies_to(self, value):
        if self.instance and value != self.instance.applies_to:
            raise serializers.ValidationError("A field describes the position or the holder, for good.")
        return value


class CommitteeFieldEntrySerializer(serializers.Serializer):
    field = CommitteeFieldSerializer(read_only=True)
    value = FieldValueField(read_only=True, allow_null=True)


class RoleRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class HolderSerializer(serializers.Serializer):
    """Who holds a position: display name only."""

    id = serializers.UUIDField()
    membership_id = serializers.UUIDField()
    display_name = serializers.CharField(source="membership.user.display_name")
    started_on = serializers.DateField()
    values = CommitteeFieldEntrySerializer(many=True)


class PositionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    order = serializers.IntegerField()
    term_start = serializers.DateField(allow_null=True)
    term_end = serializers.DateField(allow_null=True)
    grants_role = RoleRefSerializer(allow_null=True, help_text="Shown to governance staff only.")
    holder = HolderSerializer(allow_null=True)
    values = CommitteeFieldEntrySerializer(many=True)


class CommitteeSerializer(serializers.Serializer):
    can_manage = serializers.BooleanField()
    positions = PositionSerializer(many=True)


class PositionInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    term_start = serializers.DateField(required=False, allow_null=True)
    term_end = serializers.DateField(required=False, allow_null=True)
    grants_role = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        instance = self.context.get("position")
        start = attrs.get("term_start", instance.term_start if instance else None)
        end = attrs.get("term_end", instance.term_end if instance else None)
        if start and end and end < start:
            raise serializers.ValidationError({"term_end": "The term ends before it starts."})
        return attrs


class ReorderSerializer(serializers.Serializer):
    positions = serializers.ListField(child=serializers.UUIDField(), max_length=MAX_POSITIONS)


class AssignHolderSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
    started_on = serializers.DateField(required=False, allow_null=True)


class PastHolderSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    position = serializers.CharField(source="position.name")
    display_name = serializers.CharField(source="membership.user.display_name")
    started_on = serializers.DateField()
    ended_on = serializers.DateField()
    end_reason = serializers.ChoiceField(choices=EndReason.choices)


class CandidateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField(source="user.display_name")


# --- Reading ---------------------------------------------------------------------------------------------


def committee_data(organization: Organization, staff: bool) -> dict:
    fields = list(active_fields(organization, staff=staff))
    by_kind = {kind: [f for f in fields if f.applies_to == kind] for kind in CommitteeField.AppliesTo.values}
    current = PositionHolder.objects.filter(ended_at__isnull=True).select_related("membership__user")
    positions = (
        active_positions(organization)
        .select_related("grants_role")
        .prefetch_related(
            Prefetch("holders", queryset=current, to_attr="current"),
            Prefetch("field_values", to_attr="own_values"),
        )
    )
    holder_values = {}
    for value in CommitteeFieldValue.objects.filter(
        holder__position__organization=organization, holder__ended_at__isnull=True
    ):
        holder_values.setdefault(value.holder_id, {})[value.field_id] = value.value

    def entries(values: dict, kind: str) -> list[dict]:
        return [{"field": field, "value": values.get(field.id)} for field in by_kind[kind]]

    result = []
    for position in positions:
        holding = position.current[0] if position.current else None
        result.append(
            {
                "id": position.id,
                "name": position.name,
                "order": position.order,
                "term_start": position.term_start,
                "term_end": position.term_end,
                "grants_role": position.grants_role if staff else None,
                "holder": None
                if holding is None
                else {
                    "id": holding.id,
                    "membership_id": holding.membership_id,
                    "membership": holding.membership,
                    "started_on": holding.started_on,
                    "values": entries(holder_values.get(holding.id, {}), CommitteeField.AppliesTo.HOLDER),
                },
                "values": entries(
                    {v.field_id: v.value for v in position.own_values}, CommitteeField.AppliesTo.POSITION
                ),
            }
        )
    return {"can_manage": staff, "positions": result}


def committee_response(organization: Organization, staff: bool, code=status.HTTP_200_OK) -> Response:
    return Response(CommitteeSerializer(committee_data(organization, staff)).data, status=code)


# --- Views ---------------------------------------------------------------------------------------------


class CommitteeBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def position(self, organization: Organization) -> CommitteePosition:
        return get_object_or_404(
            active_positions(organization).select_for_update(of=("self",)).select_related("grants_role"),
            pk=self.kwargs["pk"],
        )


class CommitteeView(CommitteeBaseView):
    """GET /organizations/{id}/committee/: the current committee, for any member."""

    @extend_schema(responses={200: CommitteeSerializer})
    def get(self, request, organization_pk):
        organization = self.organization()
        require_membership(request.user, organization)
        return committee_response(organization, is_governance_staff(request.user, organization))


class CommitteeHistoryView(GenericAPIView):
    """Past holders of every position, newest first, for any member: display names and dates only."""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    serializer_class = PastHolderSerializer

    @extend_schema(responses={200: PastHolderSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_membership(request.user, organization)
        past = (
            PositionHolder.objects.filter(position__organization=organization, ended_at__isnull=False)
            .select_related("position", "membership__user")
            .order_by("-ended_on", "-ended_at")
        )
        page = self.paginate_queryset(past)
        return self.get_paginated_response(PastHolderSerializer(page, many=True).data)


class CommitteeCandidatesView(GenericAPIView):
    """Active members who can hold a position, for governance staff choosing a holder."""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    serializer_class = CandidateSerializer

    @extend_schema(
        parameters=[OpenApiParameter("search", str, description="Display name")],
        responses={200: CandidateSerializer(many=True)},
    )
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, GOVERNANCE)
        members = (
            organization.memberships.active()
            .filter(user__is_active=True)
            .select_related("user")
            .order_by("user__display_name", "joined_at")
        )
        term = search_term(request)
        if term:
            members = members.filter(user__display_name__icontains=term)
        page = self.paginate_queryset(members)
        return self.get_paginated_response(CandidateSerializer(page, many=True).data)


def _save_position(save):
    try:
        with transaction.atomic():
            return save()
    except IntegrityError as error:  # case-insensitive unique name among active positions
        raise ValidationError({"name": "Another position already has this name."}) from error


class PositionsView(CommitteeBaseView):
    """POST /committee/positions/: add a position at the end of the committee."""

    @extend_schema(request=PositionInputSerializer, responses={201: CommitteeSerializer})
    def post(self, request, organization_pk):
        organization = self.organization()
        body = PositionInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, GOVERNANCE)
            if active_positions(organization).count() >= MAX_POSITIONS:
                raise ApiException(
                    "too_many_positions", f"A committee can have {MAX_POSITIONS} positions.", 409
                )
            role = _grantable(organization, data.get("grants_role"))
            _guard_role(granted, role)
            last = active_positions(organization).aggregate(last=Max("order"))["last"]
            _save_position(
                lambda: CommitteePosition.objects.create(
                    organization=organization,
                    name=data["name"],
                    order=0 if last is None else last + 1,
                    term_start=data.get("term_start"),
                    term_end=data.get("term_end"),
                    grants_role=role,
                )
            )
        return committee_response(organization, True, status.HTTP_201_CREATED)


class ReorderPositionsView(CommitteeBaseView):
    """POST /committee/positions/reorder/: every active position's id, in the order to show them."""

    @extend_schema(request=ReorderSerializer, responses={200: CommitteeSerializer})
    def post(self, request, organization_pk):
        organization = self.organization()
        body = ReorderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        wanted = body.validated_data["positions"]
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, GOVERNANCE)
            positions = {p.id: p for p in active_positions(organization).select_for_update()}
            if len(wanted) != len(set(wanted)) or set(wanted) != set(positions):
                raise ValidationError({"positions": "List every position of the committee once."})
            for index, position_id in enumerate(wanted):
                position = positions[position_id]
                if position.order != index:
                    position.order = index
                    position.save(update_fields=["order"])
        return committee_response(organization, True)


class PositionView(CommitteeBaseView):
    """PATCH /committee/positions/{id}/: rename, set the term or change the granted role."""

    @extend_schema(request=PositionInputSerializer(partial=True), responses={200: CommitteeSerializer})
    def patch(self, request, organization_pk, pk):
        organization = self.organization()
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, GOVERNANCE)
            position = self.position(organization)
            body = PositionInputSerializer(data=request.data, partial=True, context={"position": position})
            body.is_valid(raise_exception=True)
            data = body.validated_data
            if "grants_role" in data:
                role = _grantable(organization, data["grants_role"])
                if role != position.grants_role:
                    _guard_role(granted, position.grants_role)
                    _guard_role(granted, role)
                    position.grants_role = role
            for name in ("name", "term_start", "term_end"):
                if name in data:
                    setattr(position, name, data[name])
            _save_position(position.save)
        return committee_response(organization, True)


class RetirePositionView(CommitteeBaseView):
    """POST /committee/positions/{id}/retire/: remove a position; its holders stay in the history."""

    @extend_schema(request=None, responses={200: CommitteeSerializer})
    def post(self, request, organization_pk, pk):
        organization = self.organization()
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, GOVERNANCE)
            position = self.position(organization)
            holding = current_holding(position)
            if holding is not None:
                _guard_role(granted, position.grants_role)
                _end(holding, EndReason.POSITION_RETIRED, local_today(organization))
            position.retired_at = timezone.now()
            position.save(update_fields=["retired_at"])
        return committee_response(organization, True)


class PositionHolderView(CommitteeBaseView):
    """PUT /committee/positions/{id}/holder/ assigns a holder (replacing the current one); DELETE ends
    the current holder's time, as stepping down."""

    @extend_schema(request=AssignHolderSerializer, responses={200: CommitteeSerializer})
    def put(self, request, organization_pk, pk):
        organization = self.organization()
        body = AssignHolderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, GOVERNANCE)
            position = self.position(organization)
            assign(
                organization,
                granted,
                request.user,
                position,
                body.validated_data["membership_id"],
                body.validated_data.get("started_on"),
            )
        return committee_response(organization, True)

    @extend_schema(request=None, responses={200: CommitteeSerializer})
    def delete(self, request, organization_pk, pk):
        organization = self.organization()
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, GOVERNANCE)
            position = self.position(organization)
            holding = current_holding(position)
            if holding is None:
                raise ApiException("vacant", "Nobody holds this position.", 409)
            _guard_role(granted, position.grants_role)
            _end(holding, EndReason.STEPPED_DOWN, local_today(organization))
        return committee_response(organization, True)


class PositionValuesView(CommitteeBaseView):
    """PATCH /committee/positions/{id}/values/: custom field values of the position and its holder."""

    @extend_schema(request=MemberFieldValuesSerializer, responses={200: CommitteeSerializer})
    def patch(self, request, organization_pk, pk):
        organization = self.organization()
        body = MemberFieldValuesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, GOVERNANCE)
            position = self.position(organization)
            write_values(organization, position, True, body.validated_data["values"], request.user)
        return committee_response(organization, True)


class CommitteeFieldsView(CommitteeBaseView):
    """GET (every definition, retired ones too) and POST committee fields, for governance staff."""

    @extend_schema(responses={200: CommitteeFieldSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = self.organization()
        require_permission(request.user, organization, GOVERNANCE)
        return Response(CommitteeFieldSerializer(organization.committee_fields.all(), many=True).data)

    @extend_schema(request=CommitteeFieldSerializer, responses={201: CommitteeFieldSerializer})
    def post(self, request, organization_pk):
        organization = self.organization()
        body = CommitteeFieldSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, GOVERNANCE)
            _ensure_room(organization)
            field = _save_field(lambda: body.save(organization=organization))
        return Response(CommitteeFieldSerializer(field).data, status=status.HTTP_201_CREATED)


def _ensure_room(organization: Organization) -> None:
    if active_fields(organization, staff=True).count() >= MAX_FIELDS:
        raise ApiException(
            "too_many_fields", f"A committee can have {MAX_FIELDS} fields. Retire one first.", 409
        )


def _save_field(save):
    try:
        with transaction.atomic():
            return save()
    except IntegrityError as error:
        raise ValidationError({"label": "Another committee field already has this label."}) from error


class CommitteeFieldBaseView(CommitteeBaseView):
    def field(self, organization: Organization) -> CommitteeField:
        return get_object_or_404(
            CommitteeField.objects.select_for_update(), pk=self.kwargs["pk"], organization=organization
        )


class CommitteeFieldView(CommitteeFieldBaseView):
    @extend_schema(request=CommitteeFieldSerializer, responses={200: CommitteeFieldSerializer})
    def patch(self, request, organization_pk, pk):
        organization = self.organization()
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, GOVERNANCE)
            field = self.field(organization)
            if field.retired_at:
                raise ApiException("field_retired", "Restore this field before changing it.", 409)
            body = CommitteeFieldSerializer(field, data=request.data, partial=True)
            body.is_valid(raise_exception=True)
            field = _save_field(body.save)
        return Response(CommitteeFieldSerializer(field).data)


class CommitteeFieldRetireView(CommitteeFieldBaseView):
    retired = True

    @extend_schema(request=None, responses={200: CommitteeFieldSerializer})
    def post(self, request, organization_pk, pk):
        organization = self.organization()
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, GOVERNANCE)
            field = self.field(organization)
            if bool(field.retired_at) != self.retired:  # repeating the request is harmless
                if not self.retired:
                    _ensure_room(organization)
                field.retired_at = timezone.now() if self.retired else None
                try:
                    with transaction.atomic():
                        field.save(update_fields=["retired_at"])
                except IntegrityError as error:
                    raise ApiException(
                        "label_taken", "Another field uses this label now. Rename that one first.", 409
                    ) from error
        return Response(CommitteeFieldSerializer(field).data)


class CommitteeFieldRestoreView(CommitteeFieldRetireView):
    retired = False
