"""Representatives (REQ-045, TASK-108).

A club nominates active members to its region's body, and a regional body nominates its own to the
country's body. The receiving body accepts or declines and may cap how many each sender has with it at
once. The sender recalls or replaces a representative; leaving the sender ends it. Everything needs
`governance.manage` in the organization acting; members read who represents them.

A representative is not a member of the body and holds no permission there. The body is shown a display
name and the organization they speak for, nothing else about the person.
"""

from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from notifications.models import Category
from notifications.service import notify

from .access import effective_permissions, lock_organization, require_membership, require_permission
from .committee import local_today
from .handover import OrganizationRefSerializer, PersonSerializer, admin_memberships
from .models import Membership, Organization, Representative
from .permissions import Permission

Status = Representative.Status
EndReason = Representative.EndReason
OPEN = (Status.PENDING, Status.ACCEPTED)
MAX_CAP = 20
# The most rows one list returns: open ones first, then the latest closed.
MAX_OPEN = 200
MAX_CLOSED = 50
LINK = "/club/representatives"
CLUB_KINDS = (Organization.Kind.CLUB, Organization.Kind.CLUB_FACILITY)


def senders_of(body: Organization):
    """The organizations that send representatives to `body`: a region's clubs, or a country's regional
    bodies. The other side of `body_for`."""
    if not body.country:
        return Organization.objects.none()
    here = Organization.objects.filter(country=body.country)
    if body.kind == Organization.Kind.REGIONAL_BODY and body.region:
        return here.filter(kind__in=CLUB_KINDS, region__iexact=body.region)
    if body.kind == Organization.Kind.NATIONAL_BODY:
        return here.filter(kind=Organization.Kind.REGIONAL_BODY)
    return Organization.objects.none()


def body_for(sender: Organization) -> Organization | None:
    """Where the organization sends representatives: a club to its region's body, a regional body to
    its country's. Nothing for any other kind, or where the body hasn't been created."""
    if not sender.country:
        return None
    bodies = Organization.objects.filter(country=sender.country)
    if sender.kind in CLUB_KINDS and sender.region:
        return bodies.filter(kind=Organization.Kind.REGIONAL_BODY, region__iexact=sender.region).first()
    if sender.kind == Organization.Kind.REGIONAL_BODY:
        return bodies.filter(kind=Organization.Kind.NATIONAL_BODY).first()
    return None


def _in_term(today: date) -> Q:
    return Q(term_end__isnull=True) | Q(term_end__gte=today)


def _taking_a_place(body: Organization, sender: Organization, today: date):
    """What counts towards the cap: nominations awaiting a decision and representatives in term."""
    return Representative.objects.filter(body=body, sender=sender).filter(
        Q(status=Status.PENDING) | (Q(status=Status.ACCEPTED) & _in_term(today))
    )


def _end(representative: Representative, reason: str, *, by=None, note: str = "") -> None:
    pending = representative.status == Status.PENDING
    representative.status = Status.WITHDRAWN if pending else Status.ENDED
    representative.end_reason = "" if pending else reason
    representative.ended_at = timezone.now()
    representative.note = note or representative.note
    if by is not None and reason == EndReason.REMOVED:
        representative.decided_by = by
    representative.save(update_fields=["status", "end_reason", "ended_at", "note", "decided_by"])


def _tell(representative: Representative, title: str, *, also=()) -> None:
    notify(
        [representative.user_id, *also],
        Category.GOVERNANCE,
        title,
        subject=f"representative:{representative.id}",
        version=representative.status + representative.end_reason,
        link=LINK,
        organization=representative.sender,
    )


def end_on_leaving(membership: Membership) -> None:
    """A member who leaves no longer speaks for the organization. Call with the organization locked."""
    leaving = Representative.objects.select_for_update().filter(
        sender=membership.organization_id, user=membership.user_id, status__in=OPEN
    )
    for representative in leaving:
        _end(representative, EndReason.LEFT)


def nominate(sender: Organization, actor, *, membership_id, term_start, term_end, replaces) -> Representative:
    body = body_for(sender)
    if body is None:
        raise ApiException("no_body", "There is no governing body to send a representative to yet.", 409)
    lock_organization(body)
    nominee = (
        Membership.objects.active()
        .filter(organization=sender, pk=membership_id, user__is_active=True)
        .first()
    )
    if nominee is None:
        raise ApiException("not_a_member", "Choose an active member of this organization.", 400)
    today = local_today(body)
    mine = Representative.objects.select_for_update().filter(body=body, sender=sender)
    # A term that has run out frees the place and lets the same person be sent again.
    for lapsed in mine.filter(status=Status.ACCEPTED, term_end__lt=today):
        _end(lapsed, EndReason.TERM_ENDED)
    replaced = None
    if replaces is not None:
        replaced = mine.filter(pk=replaces, status=Status.ACCEPTED).first()
        if replaced is None:
            raise ApiException("not_replaceable", "Choose one of your current representatives.", 400)
        if replaced.user_id == nominee.user_id:
            raise ApiException("same_person", "Choose somebody else to take over.", 400)
    if mine.filter(user=nominee.user_id, status__in=OPEN).exists():
        raise ApiException("already_nominated", "That member is already nominated or representing.", 409)
    taken = _taking_a_place(body, sender, today)
    if replaced is not None:
        taken = taken.exclude(pk=replaced.pk)
    if body.representative_cap is not None and taken.count() >= body.representative_cap:
        raise ApiException(
            "over_cap",
            f"{body.name} takes at most {body.representative_cap} from each organization. "
            "Replace or recall one first.",
            409,
        )
    representative = Representative.objects.create(
        body=body,
        sender=sender,
        user=nominee.user,
        term_start=term_start,
        term_end=term_end,
        replaces=replaced,
        nominated_by=actor,
    )
    _tell(
        representative,
        f"{sender.name} nominated a representative to {body.name}",
        also=[admin.user_id for admin in admin_memberships(body)],
    )
    return representative


def withdraw(sender: Organization, pk) -> Representative:
    """The sender takes a nomination back, or recalls a representative."""
    representative = get_object_or_404(Representative.objects.select_for_update(), pk=pk, sender=sender)
    if representative.status not in OPEN:
        raise ApiException("already_closed", "That nomination is already closed.", 409)
    _end(representative, EndReason.RECALLED)
    return representative


def decide(body: Organization, actor, pk, *, accept: bool, note: str = "") -> Representative:
    lock_organization(body)
    representative = get_object_or_404(
        Representative.objects.select_for_update().select_related("sender", "body"), pk=pk, body=body
    )
    if representative.status != Status.PENDING:
        raise ApiException("already_decided", "That nomination is no longer open.", 409)
    representative.decided_by = actor
    representative.decided_at = timezone.now()
    if not accept:
        representative.status = Status.DECLINED
        representative.note = note
        representative.save(update_fields=["status", "note", "decided_by", "decided_at"])
        _tell(representative, f"{body.name} declined the nomination", also=[representative.nominated_by_id])
        return representative
    still_member = (
        Membership.objects.active()
        .filter(organization=representative.sender_id, user=representative.user_id, user__is_active=True)
        .exists()
    )
    if not still_member:
        raise ApiException("nomination_lapsed", "The nominee is no longer an active member there.", 409)
    today = local_today(body)
    if representative.term_end and representative.term_end < today:
        raise ApiException("term_over", "The proposed term has already ended.", 409)
    replaced = None
    if representative.replaces_id:
        replaced = (
            Representative.objects.select_for_update()
            .filter(pk=representative.replaces_id, status=Status.ACCEPTED)
            .first()
        )
    seated = Representative.objects.filter(body=body, sender=representative.sender_id).filter(
        Q(status=Status.ACCEPTED) & _in_term(today)
    )
    if replaced is not None:
        seated = seated.exclude(pk=replaced.pk)
    if body.representative_cap is not None and seated.count() >= body.representative_cap:
        raise ApiException(
            "over_cap",
            f"{representative.sender.name} already has {body.representative_cap} here.",
            409,
        )
    if replaced is not None:
        _end(replaced, EndReason.REPLACED)
        _tell(replaced, f"You no longer represent {representative.sender.name} at {body.name}")
    representative.status = Status.ACCEPTED
    representative.save(update_fields=["status", "decided_by", "decided_at"])
    _tell(
        representative,
        f"{body.name} accepted the representative of {representative.sender.name}",
        also=[representative.nominated_by_id],
    )
    return representative


def remove(body: Organization, actor, pk, note: str) -> Representative:
    """The body ends an accepted representative's place."""
    representative = get_object_or_404(
        Representative.objects.select_for_update().select_related("sender", "body"), pk=pk, body=body
    )
    if representative.status != Status.ACCEPTED:
        raise ApiException("not_a_representative", "That person is not a current representative.", 409)
    _end(representative, EndReason.REMOVED, by=actor, note=note)
    _tell(
        representative, f"{body.name} ended a representative's place", also=[representative.nominated_by_id]
    )
    return representative


# --- API ---------------------------------------------------------------------------------------------


class Strict(serializers.Serializer):
    """Refuses fields it doesn't know."""

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class RepresentativeSerializer(serializers.Serializer):
    """What either side sees of a representative: a display name and the two organizations."""

    id = serializers.UUIDField()
    person = PersonSerializer(source="user")
    sender = OrganizationRefSerializer()
    body = OrganizationRefSerializer()
    status = serializers.ChoiceField(choices=Status.choices)
    end_reason = serializers.ChoiceField(choices=[("", ""), *EndReason.choices])
    term_start = serializers.DateField(allow_null=True)
    term_end = serializers.DateField(allow_null=True)
    in_term = serializers.SerializerMethodField()
    replaces = serializers.UUIDField(source="replaces_id", allow_null=True)
    note = serializers.CharField()
    created_at = serializers.DateTimeField()
    decided_at = serializers.DateTimeField(allow_null=True)
    ended_at = serializers.DateTimeField(allow_null=True)

    def get_in_term(self, representative) -> bool:
        return representative.term_end is None or representative.term_end >= self.context["today"]


class RepresentativesSerializer(serializers.Serializer):
    """`sent`: who this organization sends to `body`, whose limit is `cap`. `received`: for a governing
    body, who is sent to it, limited to `own_cap` each. Staff also get nominations and history."""

    can_manage = serializers.BooleanField()
    body = OrganizationRefSerializer(allow_null=True)
    cap = serializers.IntegerField(allow_null=True)
    sent = RepresentativeSerializer(many=True)
    receives = serializers.BooleanField()
    own_cap = serializers.IntegerField(allow_null=True)
    received = RepresentativeSerializer(many=True)


class NominateRepresentativeSerializer(Strict):
    membership_id = serializers.UUIDField()
    term_start = serializers.DateField(required=False, allow_null=True, default=None)
    term_end = serializers.DateField(required=False, allow_null=True, default=None)
    replaces = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start, end = attrs.get("term_start"), attrs.get("term_end")
        if start and end and end < start:
            raise serializers.ValidationError({"term_end": "The term ends after it starts."})
        return attrs


class RepresentativeNoteSerializer(Strict):
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class RepresentativeCapSerializer(Strict):
    cap = serializers.IntegerField(min_value=1, max_value=MAX_CAP, allow_null=True)


def _rows():
    return Representative.objects.select_related("user", "sender", "body")


def _listed(rows, user, staff: bool, today: date) -> list[Representative]:
    """Open rows, then the latest closed ones. Without the governance permission: representatives in
    term, and the caller's own rows."""
    if not staff:
        rows = rows.filter((Q(status=Status.ACCEPTED) & _in_term(today)) | Q(user=user))
    open_rows = list(rows.filter(status__in=OPEN).order_by("sender__name", "created_at")[:MAX_OPEN])
    closed = list(rows.exclude(status__in=OPEN)[:MAX_CLOSED]) if staff else []
    return [*open_rows, *closed]


def _one(representative: Representative, organization: Organization, code=status.HTTP_200_OK) -> Response:
    context = {"today": local_today(organization)}
    return Response(RepresentativeSerializer(_rows().get(pk=representative.pk), context=context).data, code)


class RepresentativesView(APIView):
    """GET: who represents this organization and, for a body, who is sent to it. POST: nominate."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RepresentativesSerializer})
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_membership(request.user, organization)
        staff = Permission.GOVERNANCE_MANAGE in effective_permissions(request.user, organization)
        today = local_today(organization)
        body = body_for(organization)
        sent = _listed(_rows().filter(sender=organization), request.user, staff, today) if body else []
        received = (
            _listed(_rows().filter(body=organization), request.user, staff, today)
            if organization.is_body
            else []
        )
        data = {
            "can_manage": staff,
            "body": body,
            "cap": body.representative_cap if body else None,
            "sent": sent,
            "receives": organization.is_body,
            "own_cap": organization.representative_cap if organization.is_body else None,
            "received": received,
        }
        return Response(RepresentativesSerializer(data, context={"today": today}).data)

    @extend_schema(request=NominateRepresentativeSerializer, responses={201: RepresentativeSerializer})
    def post(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, Permission.GOVERNANCE_MANAGE)
        body = NominateRepresentativeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                representative = nominate(organization, request.user, **body.validated_data)
        except IntegrityError as error:
            raise ApiException(
                "already_nominated", "That member is already nominated or representing.", 409
            ) from error
        return _one(representative, organization, status.HTTP_201_CREATED)


class RepresentativeActionView(APIView):
    permission_classes = [IsAuthenticated]

    def act(self, organization: Organization, request, pk) -> Representative:
        raise NotImplementedError

    def post(self, request, organization_pk, pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, Permission.GOVERNANCE_MANAGE)
        with transaction.atomic():
            representative = self.act(organization, request, pk)
        return _one(representative, organization)

    def note(self, request) -> str:
        body = RepresentativeNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return body.validated_data["note"]


class WithdrawView(RepresentativeActionView):
    """The sending organization takes back a nomination or recalls its representative."""

    @extend_schema(request=None, responses={200: RepresentativeSerializer})
    def post(self, request, organization_pk, pk):
        return super().post(request, organization_pk, pk)

    def act(self, organization, request, pk):
        return withdraw(organization, pk)


class AcceptView(RepresentativeActionView):
    """The receiving body accepts a nomination."""

    @extend_schema(request=None, responses={200: RepresentativeSerializer})
    def post(self, request, organization_pk, pk):
        return super().post(request, organization_pk, pk)

    def act(self, organization, request, pk):
        return decide(organization, request.user, pk, accept=True)


class DeclineView(RepresentativeActionView):
    """The receiving body declines a nomination, with an optional note to the sender."""

    @extend_schema(request=RepresentativeNoteSerializer, responses={200: RepresentativeSerializer})
    def post(self, request, organization_pk, pk):
        return super().post(request, organization_pk, pk)

    def act(self, organization, request, pk):
        return decide(organization, request.user, pk, accept=False, note=self.note(request))


class RemoveView(RepresentativeActionView):
    """The receiving body ends an accepted representative's place."""

    @extend_schema(request=RepresentativeNoteSerializer, responses={200: RepresentativeSerializer})
    def post(self, request, organization_pk, pk):
        return super().post(request, organization_pk, pk)

    def act(self, organization, request, pk):
        return remove(organization, request.user, pk, self.note(request))


class RepresentativeCapSetSerializer(serializers.Serializer):
    cap = serializers.IntegerField(allow_null=True)


class CapView(APIView):
    """PUT: a governing body sets how many representatives each organization may have with it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=RepresentativeCapSerializer, responses={200: RepresentativeCapSetSerializer})
    def put(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, Permission.GOVERNANCE_MANAGE)
        if not organization.is_body:
            raise ApiException("not_a_body", "Only a regional or national body sets this limit.", 409)
        body = RepresentativeCapSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        organization.representative_cap = body.validated_data["cap"]
        organization.save(update_fields=["representative_cap"])
        return Response({"cap": organization.representative_cap})
