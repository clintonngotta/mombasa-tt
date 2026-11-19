"""One admin per organization, handed over by nomination (REQ-045, TASK-105).

The admin holds the Admin role and every permission. Nobody else can be given or lose that role through
the role editor: the admin nominates an active member, who accepts or declines; the admin can cancel
while it is pending. When the admin has left or can't act, a platform super admin appoints one directly
with a reason. Every change is a row in AdminHandover and the organization row is locked for each, so
there is never no admin or two.
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

from .access import lock_organization, require_membership, require_permission
from .models import AdminHandover, Membership, Organization
from .permissions import Permission, RoleKey

NOMINATED = "organization.admin_nominated"
Status = AdminHandover.Status


def current_admin(organization: Organization) -> Membership | None:
    return (
        Membership.objects.active()
        .filter(organization=organization, roles__key=RoleKey.ADMIN)
        .select_related("user")
        .first()
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


def _settle(handover: AdminHandover, outcome: str) -> None:
    handover.status = outcome
    handover.decided_at = timezone.now()
    handover.save(update_fields=["status", "decided_at"])


def _move(organization: Organization, to: Membership, from_: Membership | None) -> None:
    """Give `to` the Admin role and take it from `from_`, who keeps every other role."""
    admin_role = organization.roles.get(key=RoleKey.ADMIN)
    if from_ is not None:
        from_.roles.remove(admin_role)
    to.roles.add(admin_role)


def nominate(organization: Organization, actor, membership_id) -> AdminHandover:
    """The admin names a successor. A pending nomination is replaced."""
    lock_organization(organization)
    admin = current_admin(organization)
    if admin is None or admin.user_id != actor.id:
        raise ApiException("not_the_admin", "Only the organization's admin can nominate a successor.", 403)
    nominee = _member(organization, membership_id)
    if nominee.pk == admin.pk:
        raise ApiException("already_admin", "You are already the admin.", 400)
    for pending in organization.admin_handovers.select_for_update().filter(status=Status.PENDING):
        _settle(pending, Status.CANCELLED)
    handover = AdminHandover.objects.create(
        organization=organization, from_user=actor, to_user=nominee.user, created_by=actor
    )
    outbox.enqueue(NOMINATED, f"{NOMINATED}:{handover.id}", {"handover_id": str(handover.id)})
    return handover


def cancel(organization: Organization, actor) -> AdminHandover:
    lock_organization(organization)
    handover = organization.admin_handovers.select_for_update().filter(status=Status.PENDING).first()
    if handover is None:
        raise ApiException("nothing_pending", "There is no nomination to cancel.", 409)
    if handover.from_user_id != actor.id:
        raise ApiException("not_the_admin", "Only the admin who nominated can cancel.", 403)
    _settle(handover, Status.CANCELLED)
    return handover


def answer(handover_id, actor, accept: bool) -> AdminHandover:
    """The nominee accepts or declines. Acceptance needs the nominator to still be the admin."""
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
    admin = current_admin(organization)
    nominee = Membership.objects.active().filter(organization=organization, user=actor).first()
    if admin is None or admin.user_id != handover.from_user_id or nominee is None:
        raise ApiException("nomination_lapsed", "The organization has changed since you were nominated.", 409)
    _move(organization, nominee, admin)
    _settle(handover, Status.ACCEPTED)
    return handover


def appoint(organization: Organization, actor, membership_id, reason: str) -> AdminHandover:
    """A platform super admin makes a member the admin at once, for an organization whose admin is gone."""
    if not is_platform_super_admin(actor):
        raise ApiException("permission_denied", "Only a platform super admin can appoint an admin.", 403)
    lock_organization(organization)
    nominee = _member(organization, membership_id)
    admin = current_admin(organization)
    if admin is not None and admin.pk == nominee.pk:
        raise ApiException("already_admin", "That member is already the admin.", 400)
    for pending in organization.admin_handovers.select_for_update().filter(status=Status.PENDING):
        _settle(pending, Status.CANCELLED)
    _move(organization, nominee, admin)
    return AdminHandover.objects.create(
        organization=organization,
        kind=AdminHandover.Kind.APPOINTMENT,
        status=Status.ACCEPTED,
        from_user=admin.user if admin else None,
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
    by = handover.from_user.display_name if handover.from_user else "The admin"
    send_mail(
        f"You're nominated as admin of {handover.organization.name}",
        f"{by} nominated you to take over as admin of {handover.organization.name} on Coast TT. "
        "The admin manages the organization's settings, roles, committee and nominations.\n\n"
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
    """Who the admin is and any open nomination; the history only for those who manage roles."""

    admin = PersonSerializer(allow_null=True)
    pending = AdminHandoverSerializer(allow_null=True)
    history = AdminHandoverSerializer(many=True, allow_null=True)


class NominateSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()


class AppointSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


def _handovers():
    return AdminHandover.objects.select_related("organization", "from_user", "to_user", "created_by")


class OrganizationAdminView(APIView):
    """GET /organizations/{id}/admin/: any member sees who the admin is."""

    permission_classes = [IsAuthenticated]

    def get_organization(self, pk) -> Organization:
        return get_object_or_404(Organization, pk=pk)

    @extend_schema(responses={200: OrganizationAdminSerializer})
    def get(self, request, organization_pk):
        organization = self.get_organization(organization_pk)
        require_membership(request.user, organization)
        admin = current_admin(organization)
        handovers = _handovers().filter(organization=organization)
        pending = handovers.filter(status=Status.PENDING).first()
        try:
            require_permission(request.user, organization, Permission.ROLES_MANAGE)
            history = list(handovers.exclude(status=Status.PENDING)[:50])
        except ApiException:
            history = None
            if pending and request.user.id not in (pending.from_user_id, pending.to_user_id):
                pending = None
        data = {"admin": admin.user if admin else None, "pending": pending, "history": history}
        return Response(OrganizationAdminSerializer(data).data)


class OrganizationAdminActionView(APIView):
    permission_classes = [IsAuthenticated]
    action_name = ""

    @extend_schema(request=NominateSerializer, responses={201: AdminHandoverSerializer})
    def post(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        with transaction.atomic():
            if self.action_name == "cancel":
                handover = cancel(organization, request.user)
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
                        handover = nominate(organization, request.user, body.validated_data["membership_id"])
                except IntegrityError as error:
                    raise ApiException("nothing_pending", "Another nomination was just made.", 409) from error
                code = status.HTTP_201_CREATED
        return Response(AdminHandoverSerializer(_handovers().get(pk=handover.pk)).data, status=code)


class NominateAdminView(OrganizationAdminActionView):
    action_name = "nominate"


class CancelNominationView(OrganizationAdminActionView):
    action_name = "cancel"

    @extend_schema(request=None, responses={200: AdminHandoverSerializer})
    def post(self, request, organization_pk):
        return super().post(request, organization_pk)


class AppointAdminView(OrganizationAdminActionView):
    action_name = "appoint"

    @extend_schema(request=AppointSerializer, responses={201: AdminHandoverSerializer})
    def post(self, request, organization_pk):
        return super().post(request, organization_pk)


class MyAdminNominationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Open nominations naming the signed-in player as an organization's next admin."""

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
