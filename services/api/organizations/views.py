from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, Q, When
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term
from core.permissions import is_platform_super_admin

from .access import (
    effective_permissions,
    ensure_admin_remains,
    lock_organization,
    managed_organizations,
    membership_permissions,
    official_for,
    require_membership,
    require_permission,
    require_within_authority,
    roles_permissions,
)
from .emails import send_invitation_email
from .member_fields import MAX_ACTIVE_FIELDS, entries, visible_fields, write_values
from .models import (
    Invitation,
    JoinRequest,
    MemberField,
    Membership,
    Organization,
    Role,
    invitation_expiry,
    seed_roles,
)
from .permissions import ALL_PERMISSIONS, ROLE_TEMPLATES, Permission, RoleKey
from .serializers import (
    InvitationCreateSerializer,
    InvitationSerializer,
    JoinRequestSerializer,
    ManagementOrganizationSerializer,
    MemberFieldEntrySerializer,
    MemberFieldSerializer,
    MemberFieldValuesSerializer,
    MemberRolesSerializer,
    MemberSerializer,
    MembershipSerializer,
    MyInvitationSerializer,
    MyJoinRequestSerializer,
    OrganizationLocationSerializer,
    OrganizationSerializer,
    PermissionInfoSerializer,
    RoleSerializer,
)

MANAGE_MEMBERS = Permission.MEMBERS_MANAGE
MANAGE_ROLES = Permission.ROLES_MANAGE


def settle(record, outcome: str, **fields) -> None:
    """Close a pending join request or invitation: set its outcome and decision time (plus any extra
    fields, e.g. who decided) and save just those columns."""
    record.status = outcome
    record.decided_at = timezone.now()
    for name, value in fields.items():
        setattr(record, name, value)
    record.save(update_fields=["status", "decided_at", *fields])


def join(organization: Organization, user) -> Membership:
    """Make `user` an active member. A returning former member (even a former admin) rejoins with no roles,
    never with old authority; an existing active membership is left untouched."""
    membership, created = Membership.objects.select_for_update().get_or_create(
        organization=organization, user=user
    )
    if not created and membership.status != Membership.Status.ACTIVE:
        membership.status = Membership.Status.ACTIVE
        membership.save(update_fields=["status"])
        membership.roles.clear()
    return membership


def leave(organization: Organization, membership: Membership) -> None:
    """End a membership, dropping its roles. Refuses to remove the last admin. Locks the organization."""
    lock_organization(organization)
    ensure_admin_remains(organization, membership)
    membership.status = Membership.Status.LEFT
    membership.save(update_fields=["status"])
    membership.roles.clear()


class OrganizationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Search, view and register organizations (REQ-004)."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    queryset = Organization.objects.all()

    @extend_schema(parameters=[OpenApiParameter("search", str, description="Name or town")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        term = search_term(self.request)
        if term:
            queryset = queryset.filter(
                Q(name__icontains=term) | Q(town__icontains=term) | Q(region__icontains=term)
            )
        return queryset

    @extend_schema(request=OrganizationLocationSerializer, responses={200: OrganizationSerializer})
    @transaction.atomic
    def partial_update(self, request, pk):
        organization = get_object_or_404(Organization.objects.select_for_update(), pk=pk)
        require_permission(request.user, organization, MANAGE_ROLES)
        serializer = OrganizationLocationSerializer(organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        moving = data.get("country", organization.country) != organization.country or (
            data.get("region", organization.region).lower() != organization.region.lower()
        )
        if organization.country and moving and not is_platform_super_admin(request.user):
            raise ApiException("permission_denied", "Ask a platform super admin to change the club's jurisdiction.", 403)
        serializer.save()
        return Response(OrganizationSerializer(organization).data)

    @transaction.atomic
    def perform_create(self, serializer):
        organization = serializer.save(created_by=self.request.user)
        roles = seed_roles(organization)
        # The creator becomes the first admin.
        membership = Membership.objects.create(organization=organization, user=self.request.user)
        membership.roles.add(roles[RoleKey.ADMIN])


class JoinRequestViewSet(viewsets.GenericViewSet):
    """Join requests for one organization (REQ-004). Any signed-in player can ask to join; only
    members holding members.manage can list or decide requests. Routes are mapped explicitly in urls.py."""

    serializer_class = JoinRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    @extend_schema(responses={200: JoinRequestSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_permission(request.user, organization, MANAGE_MEMBERS)
        pending = organization.join_requests.filter(status=JoinRequest.Status.PENDING).select_related("user")
        page = self.paginate_queryset(pending)
        return self.get_paginated_response(JoinRequestSerializer(page, many=True).data)

    @extend_schema(request=None, responses={201: MyJoinRequestSerializer, 200: MyJoinRequestSerializer})
    def create(self, request, organization_pk):
        organization = self.get_organization()
        if Membership.objects.active().filter(organization=organization, user=request.user).exists():
            raise ApiException("already_member", "You're already a member of this organization.", 409)

        existing = JoinRequest.objects.filter(
            organization=organization, user=request.user, status=JoinRequest.Status.PENDING
        ).first()
        if existing:  # asking twice is harmless
            return Response(MyJoinRequestSerializer(existing).data)
        try:
            with transaction.atomic():
                join_request = JoinRequest.objects.create(organization=organization, user=request.user)
        except IntegrityError:  # a concurrent duplicate won the race
            join_request = JoinRequest.objects.get(
                organization=organization, user=request.user, status=JoinRequest.Status.PENDING
            )
            return Response(MyJoinRequestSerializer(join_request).data)
        return Response(MyJoinRequestSerializer(join_request).data, status=status.HTTP_201_CREATED)

    def _decide(self, request, organization_pk, pk, outcome):
        organization = self.get_organization()
        with transaction.atomic():
            # The organization lock orders this after any concurrent role change, so someone whose role
            # was just removed can't still decide.
            lock_organization(organization)
            require_permission(request.user, organization, MANAGE_MEMBERS)
            join_request = get_object_or_404(
                JoinRequest.objects.select_for_update(), pk=pk, organization=organization
            )
            if join_request.status != JoinRequest.Status.PENDING:
                raise ApiException("already_decided", "This request has already been decided.", 409)
            settle(join_request, outcome, decided_by=request.user)
            if outcome == JoinRequest.Status.APPROVED:
                join(organization, join_request.user)
        return Response(JoinRequestSerializer(join_request).data)

    @extend_schema(request=None, responses={200: JoinRequestSerializer})
    def approve(self, request, organization_pk, pk):
        return self._decide(request, organization_pk, pk, JoinRequest.Status.APPROVED)

    @extend_schema(request=None, responses={200: JoinRequestSerializer})
    def reject(self, request, organization_pk, pk):
        return self._decide(request, organization_pk, pk, JoinRequest.Status.REJECTED)


class InvitationViewSet(viewsets.GenericViewSet):
    """Email invitations for one organization (REQ-004), for members holding members.manage. Inviting an
    address never reveals whether it has an account or belongs to a member: the reply is the same and the
    email goes out either way (an existing member who accepts keeps their roles)."""

    serializer_class = InvitationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    @property
    def throttle_scope(self):
        # Each invite sends an email, so sending is rate-limited per sender.
        return "invitations" if self.action == "create" else None

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    @extend_schema(responses={200: InvitationSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_permission(request.user, organization, MANAGE_MEMBERS)
        # Lapsed invitations can't be accepted, so they aren't shown as pending.
        pending = organization.invitations.filter(
            status=Invitation.Status.PENDING, expires_at__gt=timezone.now()
        )
        page = self.paginate_queryset(pending)
        return self.get_paginated_response(InvitationSerializer(page, many=True).data)

    @extend_schema(
        request=InvitationCreateSerializer, responses={201: InvitationSerializer, 200: InvitationSerializer}
    )
    def create(self, request, organization_pk):
        organization = self.get_organization()
        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        with transaction.atomic():
            lock_organization(organization)  # ordered after concurrent role changes
            require_permission(request.user, organization, MANAGE_MEMBERS)
            invitation = (
                Invitation.objects.select_for_update()
                .filter(organization=organization, email=email, status=Invitation.Status.PENDING)
                .first()
            )
            created = invitation is None
            if created:
                try:
                    with transaction.atomic():
                        invitation = Invitation.objects.create(
                            organization=organization, email=email, invited_by=request.user
                        )
                except IntegrityError:  # a concurrent invite to the same address won the race
                    invitation = Invitation.objects.get(
                        organization=organization, email=email, status=Invitation.Status.PENDING
                    )
                    created = False
            elif not invitation.is_open:  # inviting again renews a lapsed invitation
                invitation.expires_at = invitation_expiry()
                invitation.invited_by = request.user
                invitation.save(update_fields=["expires_at", "invited_by"])
        send_invitation_email(invitation)
        return Response(
            InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED if created else 200
        )

    @extend_schema(request=None, responses={200: InvitationSerializer})
    def revoke(self, request, organization_pk, pk):
        organization = self.get_organization()
        with transaction.atomic():
            lock_organization(organization)  # ordered after concurrent role changes
            require_permission(request.user, organization, MANAGE_MEMBERS)
            invitation = get_object_or_404(
                Invitation.objects.select_for_update(), pk=pk, organization=organization
            )
            if invitation.status != Invitation.Status.PENDING:
                raise ApiException("already_decided", "This invitation has already been answered.", 409)
            settle(invitation, Invitation.Status.REVOKED)
        return Response(InvitationSerializer(invitation).data)


class MyInvitationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Open invitations addressed to the signed-in player's verified email; they accept or decline."""

    serializer_class = MyInvitationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Invitation.objects.none()
        user = self.request.user
        if not user.email_verified_at:  # an unverified address proves nothing about who owns it
            return Invitation.objects.none()
        return Invitation.objects.filter(
            email__iexact=user.email, status=Invitation.Status.PENDING, expires_at__gt=timezone.now()
        ).select_related("organization", "invited_by")

    def _answer(self, pk, outcome):
        with transaction.atomic():
            invitation = get_object_or_404(self.get_queryset().select_for_update(of=("self",)), pk=pk)
            accepted = outcome == Invitation.Status.ACCEPTED
            settle(invitation, outcome, accepted_by=self.request.user if accepted else None)
            if accepted:
                join(invitation.organization, self.request.user)
                # An open join request to the same organization is moot now. It is withdrawn, not
                # approved, so the audit trail never shows a staff decision nobody made.
                JoinRequest.objects.filter(
                    organization=invitation.organization,
                    user=self.request.user,
                    status=JoinRequest.Status.PENDING,
                ).update(status=JoinRequest.Status.WITHDRAWN, decided_at=invitation.decided_at)
        return Response(MyInvitationSerializer(invitation).data)

    @extend_schema(request=None, responses={200: MyInvitationSerializer})
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._answer(pk, Invitation.Status.ACCEPTED)

    @extend_schema(request=None, responses={200: MyInvitationSerializer})
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._answer(pk, Invitation.Status.DECLINED)


class MyManagedOrganizationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ManagementOrganizationSerializer(many=True)})
    def get(self, request):
        platform = is_platform_super_admin(request.user)
        rows = [
            {
                "organization": organization,
                "authority": "platform" if platform else "country" if official_for(request.user, organization, country_only=True) else "regional",
                "permissions": sorted(ALL_PERMISSIONS),
            }
            for organization in managed_organizations(request.user)
        ]
        return Response(ManagementOrganizationSerializer(rows, many=True).data)


class MyMembershipViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Organizations the signed-in player belongs to (the basis for the context switcher), with the roles
    and permissions they hold in each. A player can leave, unless they are its last admin."""

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no user
            return Membership.objects.none()
        return (
            Membership.objects.active()
            .filter(user=self.request.user)
            .select_related("organization")
            .prefetch_related("roles", "organization__roles")
        )

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        with transaction.atomic():
            membership = get_object_or_404(self.get_queryset(), pk=pk)
            leave(membership.organization, membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        methods=["get"],
        responses={200: MemberFieldEntrySerializer(many=True)},
        operation_id="me_memberships_fields_list",
    )
    @extend_schema(
        methods=["patch"],
        request=MemberFieldValuesSerializer,
        responses={200: MemberFieldEntrySerializer(many=True)},
    )
    @action(detail=True, methods=["get", "patch"], pagination_class=None)
    def fields(self, request, pk=None):
        """The player's own member-visible custom fields here (REQ-005). Staff-only fields never appear
        and can't be written, even by a member who knows their ids."""
        with transaction.atomic():
            membership = get_object_or_404(self.get_queryset(), pk=pk)
            if request.method == "PATCH":
                serializer = MemberFieldValuesSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                lock_organization(membership.organization)  # ordered after field changes
                write_values(
                    membership,
                    visible_fields(membership.organization, staff=False),
                    serializer.validated_data["values"],
                    request.user,
                )
            found = entries(membership, visible_fields(membership.organization, staff=False))
        return Response(MemberFieldEntrySerializer(found, many=True).data)


class PermissionCatalogView(generics.GenericAPIView):
    """Every permission a role can hold (REQ-005), with a plain-language label for the role editor."""

    serializer_class = PermissionInfoSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    @extend_schema(responses={200: PermissionInfoSerializer(many=True)})
    def get(self, request):
        return Response([{"code": code, "label": label} for code, label in Permission.choices])


class RoleViewSet(viewsets.GenericViewSet):
    """Roles of one organization (REQ-005), for members holding roles.manage. Nobody can create, change or
    delete a role in a way that grants or removes permissions they don't hold themselves. Admin always
    has every permission and can only be renamed; Admin and Member can't be deleted."""

    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def get_role(self, organization: Organization, pk) -> Role:
        return get_object_or_404(Role.objects.select_for_update(), pk=pk, organization=organization)

    @extend_schema(responses={200: RoleSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_permission(request.user, organization, MANAGE_ROLES, MANAGE_MEMBERS)
        roles = organization.roles.annotate(
            member_count=Count("memberships", filter=Q(memberships__status=Membership.Status.ACTIVE)),
            # Templates in their usual order, custom roles by name, and Member (everyone) last.
            position=Case(
                When(key=RoleKey.MEMBER, then=len(ROLE_TEMPLATES) + 1),
                *(When(key=key, then=index) for index, (key, _, _) in enumerate(ROLE_TEMPLATES)),
                default=len(ROLE_TEMPLATES),
                output_field=IntegerField(),
            ),
        ).order_by("position", Lower("name"))
        return Response(RoleSerializer(roles, many=True).data)

    @extend_schema(request=RoleSerializer, responses={201: RoleSerializer})
    def create(self, request, organization_pk):
        organization = self.get_organization()
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, MANAGE_ROLES)
            permissions = serializer.validated_data.get("permissions", [])
            require_within_authority(granted, permissions)
            role = self._save(serializer, organization=organization, permissions=permissions)
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)  # new: no members yet

    @extend_schema(request=RoleSerializer, responses={200: RoleSerializer})
    def partial_update(self, request, organization_pk, pk):
        organization = self.get_organization()
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, MANAGE_ROLES)
            role = self.get_role(organization, pk)
            # Renaming counts too: nobody relabels authority they don't hold (e.g. renaming Admin).
            require_within_authority(granted, role.permission_set)
            serializer = RoleSerializer(role, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            if "permissions" in serializer.validated_data:
                new = frozenset(serializer.validated_data["permissions"])
                if role.is_admin and new != role.permission_set:
                    raise ApiException(
                        "admin_role_locked", "The Admin role always has every permission.", 409
                    )
                require_within_authority(granted, new)
            role = self._save(serializer)
            role.member_count = role.memberships.active().count()
        return Response(RoleSerializer(role).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, organization_pk, pk):
        organization = self.get_organization()
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, MANAGE_ROLES)
            role = self.get_role(organization, pk)
            if role.is_admin or role.is_member:
                raise ApiException("role_required", f"The {role.name} role can't be deleted.", 409)
            require_within_authority(granted, role.permission_set)
            role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _save(serializer, **extra) -> Role:
        try:
            with transaction.atomic():
                return serializer.save(**extra)
        except IntegrityError as error:  # case-insensitive unique name per organization
            raise ValidationError({"name": "Another role already has this name."}) from error


class MemberViewSet(viewsets.GenericViewSet):
    """Active members of one organization with their roles (REQ-005), for members holding members.manage
    or roles.manage. Shows display names and roles only, never email or contact details."""

    serializer_class = MemberSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def get_member(self, organization: Organization, pk) -> Membership:
        return get_object_or_404(
            Membership.objects.active()
            .select_for_update(of=("self",))
            .select_related("organization", "user")
            .prefetch_related("roles", "organization__roles"),
            pk=pk,
            organization=organization,
        )

    @extend_schema(
        parameters=[OpenApiParameter("search", str, description="Display name")],
        responses={200: MemberSerializer(many=True)},
    )
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_permission(request.user, organization, MANAGE_MEMBERS, MANAGE_ROLES)
        members = (
            organization.memberships.active()
            .select_related("user")
            .prefetch_related("roles")
            .order_by("user__display_name", "joined_at")
        )
        term = search_term(request)
        if term:
            members = members.filter(user__display_name__icontains=term)
        page = self.paginate_queryset(members)
        return self.get_paginated_response(MemberSerializer(page, many=True).data)

    @extend_schema(request=MemberRolesSerializer, responses={200: MemberSerializer})
    def set_roles(self, request, organization_pk, pk):
        """Replace a member's roles. Each role added or removed must be within the actor's authority."""
        organization = self.get_organization()
        serializer = MemberRolesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted_ids = set(serializer.validated_data["roles"])
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, MANAGE_ROLES)
            member = self.get_member(organization, pk)
            # Role IDs from another organization, and the implicit Member role, are simply unknown here.
            wanted = list(organization.roles.exclude(key=RoleKey.MEMBER).filter(pk__in=wanted_ids))
            if len(wanted) != len(wanted_ids):
                raise ValidationError({"roles": "One or more roles don't exist in this organization."})
            current = set(member.roles.all())
            changed = current.symmetric_difference(wanted)
            require_within_authority(granted, roles_permissions(changed))
            if any(role.is_admin for role in current - set(wanted)):
                ensure_admin_remains(organization, member)
            member.roles.set(wanted)
            member = self.get_member(organization, pk)  # fresh roles for the reply
        return Response(MemberSerializer(member).data)

    @extend_schema(request=None, responses={204: None})
    def remove(self, request, organization_pk, pk):
        """End someone's membership. Nobody can remove a member who holds permissions they don't."""
        organization = self.get_organization()
        with transaction.atomic():
            lock_organization(organization)
            granted = require_permission(request.user, organization, MANAGE_MEMBERS)
            member = self.get_member(organization, pk)
            require_within_authority(granted, membership_permissions(member))
            leave(organization, member)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberFieldViewSet(viewsets.GenericViewSet):
    """Custom member field definitions of one organization (REQ-005). Members holding members.manage
    create, edit, retire and restore them, see them all, and read and write any member's values. Other
    members see only the active member-visible ones, which is what they need to fill in their own details
    (through /me/memberships/{id}/fields/)."""

    serializer_class = MemberFieldSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def get_field(self, organization: Organization, pk) -> MemberField:
        return get_object_or_404(MemberField.objects.select_for_update(), pk=pk, organization=organization)

    @extend_schema(responses={200: MemberFieldSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_membership(request.user, organization)
        if MANAGE_MEMBERS in effective_permissions(request.user, organization):
            fields = organization.member_fields.all()  # retired ones too, so staff can restore them
        else:
            fields = visible_fields(organization, staff=False)
        return Response(MemberFieldSerializer(fields, many=True).data)

    @extend_schema(request=MemberFieldSerializer, responses={201: MemberFieldSerializer})
    def create(self, request, organization_pk):
        organization = self.get_organization()
        serializer = MemberFieldSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, MANAGE_MEMBERS)
            self._ensure_room(organization)
            field = self._save(serializer, organization=organization)
        return Response(MemberFieldSerializer(field).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=MemberFieldSerializer, responses={200: MemberFieldSerializer})
    def partial_update(self, request, organization_pk, pk):
        organization = self.get_organization()
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, MANAGE_MEMBERS)
            field = self.get_field(organization, pk)
            if field.retired_at:
                raise ApiException("field_retired", "Restore this field before changing it.", 409)
            serializer = MemberFieldSerializer(field, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            field = self._save(serializer)
        return Response(MemberFieldSerializer(field).data)

    @extend_schema(request=None, responses={200: MemberFieldSerializer})
    def retire(self, request, organization_pk, pk):
        """Stop using a field. It disappears from members' details; recorded values are kept."""
        return self._set_retired(request, pk, retired=True)

    @extend_schema(request=None, responses={200: MemberFieldSerializer})
    def restore(self, request, organization_pk, pk):
        return self._set_retired(request, pk, retired=False)

    def _set_retired(self, request, pk, *, retired: bool):
        organization = self.get_organization()
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, MANAGE_MEMBERS)
            field = self.get_field(organization, pk)
            if bool(field.retired_at) != retired:  # repeating the request is harmless
                if not retired:
                    self._ensure_room(organization)
                field.retired_at = timezone.now() if retired else None
                try:
                    with transaction.atomic():
                        field.save(update_fields=["retired_at"])
                except IntegrityError as error:
                    raise ApiException(
                        "label_taken", "Another field uses this label now. Rename that one first.", 409
                    ) from error
        return Response(MemberFieldSerializer(field).data)

    def get_member(self, organization: Organization, pk) -> Membership:
        return get_object_or_404(
            Membership.objects.active().select_for_update(), pk=pk, organization=organization
        )

    @extend_schema(responses={200: MemberFieldEntrySerializer(many=True)})
    def member_values(self, request, organization_pk, pk):
        """A member's custom field values, staff-only ones included, for holders of members.manage."""
        organization = self.get_organization()
        require_permission(request.user, organization, MANAGE_MEMBERS)
        member = get_object_or_404(Membership.objects.active(), pk=pk, organization=organization)
        found = entries(member, visible_fields(organization, staff=True))
        return Response(MemberFieldEntrySerializer(found, many=True).data)

    @extend_schema(
        request=MemberFieldValuesSerializer, responses={200: MemberFieldEntrySerializer(many=True)}
    )
    def set_member_values(self, request, organization_pk, pk):
        organization = self.get_organization()
        serializer = MemberFieldValuesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, MANAGE_MEMBERS)
            member = self.get_member(organization, pk)
            fields = visible_fields(organization, staff=True)
            write_values(member, fields, serializer.validated_data["values"], request.user)
            found = entries(member, fields)
        return Response(MemberFieldEntrySerializer(found, many=True).data)

    @staticmethod
    def _ensure_room(organization: Organization) -> None:
        if visible_fields(organization, staff=True).count() >= MAX_ACTIVE_FIELDS:
            raise ApiException(
                "too_many_fields",
                f"An organization can have {MAX_ACTIVE_FIELDS} member fields. Retire one first.",
                409,
            )

    @staticmethod
    def _save(serializer, **extra) -> MemberField:
        try:
            with transaction.atomic():
                return serializer.save(**extra)
        except IntegrityError as error:  # case-insensitive unique label among active fields
            raise ValidationError({"label": "Another field already has this label."}) from error


class MyJoinRequestsView(generics.ListAPIView):
    """The signed-in player's own join requests (REQ-004), newest first."""

    serializer_class = MyJoinRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return JoinRequest.objects.none()
        return (
            JoinRequest.objects.filter(user=self.request.user)
            .select_related("organization")
            .order_by("-created_at")
        )
