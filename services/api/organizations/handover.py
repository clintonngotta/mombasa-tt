"""Up to three admins per organization, changed by nomination (REQ-045, TASK-105, TASK-139).

Each admin holds the Admin role and every permission. Nobody is given or loses that role through the
role editor. An admin nominates an active member either as a further admin (while fewer than MAX_ADMINS
hold or are offered the role) or as their own successor; the nominee accepts or declines and the
nomination can be cancelled while it is pending. An admin may step down while another remains. When the
admins have left or can't act, a platform super admin appoints one directly with a reason. Every change
is a row in AdminHandover and the organization row is locked for each, so there is never no admin and
never more than MAX_ADMINS.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.pagination import StandardPagination
from core.permissions import is_platform_super_admin
from outbox import service as outbox

from .access import ensure_admin_remains, lock_organization, require_membership, require_permission
from .models import AdminHandover, Membership, Organization
from .permissions import Permission, RoleKey

NOMINATED = "organization.admin_nominated"
MAX_ADMINS = 3
Status = AdminHandover.Status
Kind = AdminHandover.Kind


def admin_memberships(organization: Organization) -> list[Membership]:
    """Everyone holding the Admin role, longest-standing first. A holder whose account is switched off
    still fills a place until a platform super admin appoints someone (see `appoint`)."""
    return list(
        Membership.objects.active()
        .filter(organization=organization, roles__key=RoleKey.ADMIN)
        .select_related("user")
        .order_by("joined_at", "pk")
    )


def _too_many() -> ApiException:
    return ApiException(
        "admin_limit", f"An organization has at most {MAX_ADMINS} admins. One must step down first.", 409
    )


def _member(organization: Organization, membership_id) -> Membership:
    membership = (
        Membership.objects.active()
        .filter(organization=organization, pk=membership_id, user__is_active=True)
        .select_related("user")
        .first()
    )
    if membership is None:
        raise ApiException("not_a_member", "Choose an active member of this organization.", 400)
    return membership


def _acting_admin(actor, admins: list[Membership], message: str) -> Membership:
    mine = next((m for m in admins if m.user_id == actor.id), None)
    if mine is None:
        raise ApiException("not_the_admin", message, 403)
    return mine


def _settle(handover: AdminHandover, outcome: str) -> None:
    handover.status = outcome
    handover.decided_at = timezone.now()
    handover.save(update_fields=["status", "decided_at"])


def _pending(organization: Organization):
    return organization.admin_handovers.select_for_update().filter(status=Status.PENDING)


def nominate(organization: Organization, actor, membership_id, kind: str = Kind.NOMINATION) -> AdminHandover:
    """An admin names a further admin (`addition`) or their own successor (`nomination`). An open
    nomination of the same member, and the admin's earlier choice of successor, are replaced."""
    lock_organization(organization)
    admins = admin_memberships(organization)
    _acting_admin(actor, admins, "Only an admin of the organization can nominate an admin.")
    nominee = _member(organization, membership_id)
    if any(m.pk == nominee.pk for m in admins):
        raise ApiException("already_admin", "That member is already an admin.", 400)
    for pending in _pending(organization):
        same_member = pending.to_user_id == nominee.user_id
        my_successor = (
            kind == Kind.NOMINATION and pending.kind == Kind.NOMINATION and pending.from_user_id == actor.id
        )
        if same_member or my_successor:
            _settle(pending, Status.CANCELLED)
    if kind == Kind.ADDITION:
        offered = _pending(organization).filter(kind=Kind.ADDITION).count()
        if len(admins) + offered >= MAX_ADMINS:
            raise _too_many()
    handover = AdminHandover.objects.create(
        organization=organization, kind=kind, from_user=actor, to_user=nominee.user, created_by=actor
    )
    outbox.enqueue(NOMINATED, f"{NOMINATED}:{handover.id}", {"handover_id": str(handover.id)})
    return handover


def cancel(organization: Organization, actor, handover_id=None) -> AdminHandover:
    """Withdraw an open nomination: the one named, else the actor's own, else the only one there is.
    Any admin withdraws an offer of a further place; a successor only the admin who chose them."""
    lock_organization(organization)
    pending = list(_pending(organization).filter(pk=handover_id) if handover_id else _pending(organization))
    pending.sort(key=lambda h: h.from_user_id != actor.id)
    if not pending:
        raise ApiException("nothing_pending", "There is no nomination to cancel.", 409)
    handover = pending[0]
    is_admin = any(m.user_id == actor.id for m in admin_memberships(organization))
    own = handover.from_user_id == actor.id
    if not is_admin or (handover.kind == Kind.NOMINATION and not own):
        raise ApiException("not_the_admin", "Only the admin who nominated can cancel.", 403)
    _settle(handover, Status.CANCELLED)
    return handover


def answer(handover_id, actor, accept: bool) -> AdminHandover:
    """The nominee accepts or declines. Acceptance needs the nominator to still be an admin."""
    handover = get_object_or_404(
        AdminHandover.objects.select_related("organization"), pk=handover_id, to_user=actor
    )
    organization = lock_organization(handover.organization)
    handover = AdminHandover.objects.select_for_update().get(pk=handover.pk)
    if handover.status != Status.PENDING:
        raise ApiException("nothing_pending", "This nomination is no longer open.", 409)
    if not accept:
        _settle(handover, Status.DECLINED)
        return handover
    admins = admin_memberships(organization)
    nominator = next((m for m in admins if m.user_id == handover.from_user_id), None)
    nominee = Membership.objects.active().filter(organization=organization, user=actor).first()
    if nominator is None or nominee is None or any(m.pk == nominee.pk for m in admins):
        raise ApiException("nomination_lapsed", "The organization has changed since you were nominated.", 409)
    admin_role = organization.roles.get(key=RoleKey.ADMIN)
    if handover.kind == Kind.NOMINATION:
        nominator.roles.remove(admin_role)  # they keep every other role
    elif len(admins) >= MAX_ADMINS:
        raise _too_many()
    nominee.roles.add(admin_role)
    _settle(handover, Status.ACCEPTED)
    return handover


def step_down(organization: Organization, actor) -> AdminHandover:
    """An admin gives up the Admin role, keeping their other roles. Refused for the last admin."""
    lock_organization(organization)
    mine = _acting_admin(actor, admin_memberships(organization), "Only an admin can step down as admin.")
    ensure_admin_remains(organization, mine)
    mine.roles.remove(organization.roles.get(key=RoleKey.ADMIN))
    for pending in _pending(organization).filter(from_user=actor):
        _settle(pending, Status.CANCELLED)
    return AdminHandover.objects.create(
        organization=organization,
        kind=Kind.STEP_DOWN,
        status=Status.ACCEPTED,
        from_user=actor,
        to_user=actor,
        created_by=actor,
        decided_at=timezone.now(),
    )


def appoint(
    organization: Organization, actor, membership_id, reason: str, replace_membership_id=None
) -> AdminHandover:
    """A platform super admin makes a member an admin at once, for an organization whose admins are gone
    or can't act. Admins whose accounts are switched off lose the role; so does the admin named in
    `replace_membership_id`, which is needed when every place is taken by a working account."""
    if not is_platform_super_admin(actor):
        raise ApiException("permission_denied", "Only a platform super admin can appoint an admin.", 403)
    lock_organization(organization)
    nominee = _member(organization, membership_id)
    admins = admin_memberships(organization)
    if any(m.pk == nominee.pk for m in admins):
        raise ApiException("already_admin", "That member is already an admin.", 400)
    replaced = None
    if replace_membership_id is not None:
        replaced = next((m for m in admins if m.pk == replace_membership_id), None)
        if replaced is None:
            raise ApiException("not_an_admin", "Choose a current admin to replace.", 400)
    leaving = [m for m in admins if not m.user.is_active or m is replaced]
    if len(admins) - len(leaving) >= MAX_ADMINS:
        raise _too_many()
    admin_role = organization.roles.get(key=RoleKey.ADMIN)
    for membership in leaving:
        membership.roles.remove(admin_role)
    gone = {m.user_id for m in leaving}
    for pending in _pending(organization):
        if pending.to_user_id == nominee.user_id or pending.from_user_id in gone:
            _settle(pending, Status.CANCELLED)
    nominee.roles.add(admin_role)
    previous = replaced or (leaving[0] if leaving else None)
    return AdminHandover.objects.create(
        organization=organization,
        kind=Kind.APPOINTMENT,
        status=Status.ACCEPTED,
        from_user=previous.user if previous else None,
        to_user=nominee.user,
        created_by=actor,
        reason=reason,
        decided_at=timezone.now(),
    )


@outbox.handler(NOMINATED)
def send_nomination(payload: dict) -> None:
    handover = (
        AdminHandover.objects.select_related("organization", "to_user", "from_user")
        .filter(pk=payload["handover_id"], status=Status.PENDING)
        .first()
    )
    if handover is None:
        return
    by = handover.from_user.display_name if handover.from_user else "An admin"
    name = handover.organization.name
    if handover.kind == Kind.ADDITION:
        subject = f"You're nominated as an admin of {name}"
        what = f"{by} nominated you as a further admin of {name} on Coast TT, alongside the current admins."
    else:
        subject = f"You're nominated as admin of {name}"
        what = f"{by} nominated you to take over from them as an admin of {name} on Coast TT."
    send_mail(
        subject,
        f"{what} An admin manages the organization's settings, roles, committee and nominations.\n\n"
        f"Accept or decline: {settings.FRONTEND_URL}/club/admin-nominations\n",
        None,
        [handover.to_user.email],
    )


# --- API ---------------------------------------------------------------------------------------------


class PersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class OrganizationRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AdminHandoverSerializer(serializers.ModelSerializer):
    from_user = PersonSerializer(allow_null=True)
    to_user = PersonSerializer()
    created_by = PersonSerializer(allow_null=True)
    organization = OrganizationRefSerializer()

    class Meta:
        model = AdminHandover
        fields = [
            "id",
            "organization",
            "kind",
            "status",
            "from_user",
            "to_user",
            "created_by",
            "reason",
            "created_at",
            "decided_at",
        ]
        read_only_fields = fields


class OrganizationAdminSerializer(serializers.Serializer):
    """Who the admins are and the open nominations; the history only for those who manage roles.
    `admin` and `pending` are the first of `admins` and `nominations`, kept for older clients."""

    admin = PersonSerializer(allow_null=True)
    admins = PersonSerializer(many=True)
    limit = serializers.IntegerField()
    pending = AdminHandoverSerializer(allow_null=True)
    nominations = AdminHandoverSerializer(many=True)
    history = AdminHandoverSerializer(many=True, allow_null=True)


class NominateSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=[Kind.NOMINATION, Kind.ADDITION], default=Kind.NOMINATION)


class CancelNominationSerializer(serializers.Serializer):
    handover_id = serializers.UUIDField(required=False)


class AppointSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=300, trim_whitespace=True)
    replace_membership_id = serializers.UUIDField(required=False)


def _handovers():
    return AdminHandover.objects.select_related("organization", "from_user", "to_user", "created_by")


class OrganizationAdminView(APIView):
    """GET /organizations/{id}/admin/: any member sees who the admins are."""

    permission_classes = [IsAuthenticated]

    def get_organization(self, pk) -> Organization:
        return get_object_or_404(Organization, pk=pk)

    @extend_schema(responses={200: OrganizationAdminSerializer})
    def get(self, request, organization_pk):
        organization = self.get_organization(organization_pk)
        require_membership(request.user, organization)
        admins = [membership.user for membership in admin_memberships(organization)]
        handovers = _handovers().filter(organization=organization)
        nominations = list(handovers.filter(status=Status.PENDING)[: MAX_ADMINS * 2])
        try:
            require_permission(request.user, organization, Permission.ROLES_MANAGE)
            history = list(handovers.exclude(status=Status.PENDING)[:50])
        except ApiException:
            history = None
            nominations = [n for n in nominations if request.user.id in (n.from_user_id, n.to_user_id)]
        data = {
            "admin": admins[0] if admins else None,
            "admins": admins,
            "limit": MAX_ADMINS,
            "pending": nominations[0] if nominations else None,
            "nominations": nominations,
            "history": history,
        }
        return Response(OrganizationAdminSerializer(data).data)


class OrganizationAdminActionView(APIView):
    permission_classes = [IsAuthenticated]
    action_name = ""

    @extend_schema(request=NominateSerializer, responses={201: AdminHandoverSerializer})
    def post(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        with transaction.atomic():
            if self.action_name == "cancel":
                body = CancelNominationSerializer(data=request.data)
                body.is_valid(raise_exception=True)
                handover = cancel(organization, request.user, body.validated_data.get("handover_id"))
                code = status.HTTP_200_OK
            elif self.action_name == "step_down":
                handover = step_down(organization, request.user)
                code = status.HTTP_200_OK
            elif self.action_name == "appoint":
                body = AppointSerializer(data=request.data)
                body.is_valid(raise_exception=True)
                handover = appoint(organization, request.user, **body.validated_data)
                code = status.HTTP_201_CREATED
            else:
                body = NominateSerializer(data=request.data)
                body.is_valid(raise_exception=True)
                try:
                    with transaction.atomic():
                        handover = nominate(organization, request.user, **body.validated_data)
                except IntegrityError as error:
                    raise ApiException("nothing_pending", "Another nomination was just made.", 409) from error
                code = status.HTTP_201_CREATED
        return Response(AdminHandoverSerializer(_handovers().get(pk=handover.pk)).data, status=code)


class NominateAdminView(OrganizationAdminActionView):
    action_name = "nominate"


class CancelNominationView(OrganizationAdminActionView):
    action_name = "cancel"

    @extend_schema(request=CancelNominationSerializer, responses={200: AdminHandoverSerializer})
    def post(self, request, organization_pk):
        return super().post(request, organization_pk)


class StepDownAdminView(OrganizationAdminActionView):
    """POST /organizations/{id}/admin/step-down/: an admin gives up the role while another remains."""

    action_name = "step_down"

    @extend_schema(request=None, responses={200: AdminHandoverSerializer})
    def post(self, request, organization_pk):
        return super().post(request, organization_pk)


class AppointAdminView(OrganizationAdminActionView):
    action_name = "appoint"

    @extend_schema(request=AppointSerializer, responses={201: AdminHandoverSerializer})
    def post(self, request, organization_pk):
        return super().post(request, organization_pk)


class MyAdminNominationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Open nominations naming the signed-in player as an admin of an organization."""

    serializer_class = AdminHandoverSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AdminHandover.objects.none()
        return _handovers().filter(to_user=self.request.user, status=Status.PENDING)

    def _answer(self, pk, accept):
        with transaction.atomic():
            handover = answer(pk, self.request.user, accept)
        return Response(AdminHandoverSerializer(_handovers().get(pk=handover.pk)).data)

    @extend_schema(request=None, responses={200: AdminHandoverSerializer})
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._answer(pk, True)

    @extend_schema(request=None, responses={200: AdminHandoverSerializer})
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._answer(pk, False)
