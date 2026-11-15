from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term

from .emails import send_invitation_email
from .models import Invitation, JoinRequest, Membership, Organization, invitation_expiry
from .serializers import (
    InvitationCreateSerializer,
    InvitationSerializer,
    JoinRequestSerializer,
    MembershipSerializer,
    MyInvitationSerializer,
    MyJoinRequestSerializer,
    OrganizationSerializer,
)


def require_admin(user, organization: Organization, what: str) -> None:
    """Placeholder admin-only gate until the permission catalog lands (TASK-013). Call it inside the
    transaction that does the work, so a concurrently removed admin can't still act."""
    if not Membership.objects.is_admin(user, organization):
        raise ApiException("not_organization_admin", f"Only organization admins can {what}.", 403)


def join(organization: Organization, user) -> Membership:
    """Make `user` an active member. A returning former member (even a former admin) rejoins as a plain
    member, never with old authority; an existing active membership is left untouched."""
    membership, created = Membership.objects.select_for_update().get_or_create(
        organization=organization, user=user
    )
    if not created and membership.status != Membership.Status.ACTIVE:
        membership.status = Membership.Status.ACTIVE
        membership.role = Membership.Role.MEMBER
        membership.save(update_fields=["status", "role"])
    return membership


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
            queryset = queryset.filter(Q(name__icontains=term) | Q(town__icontains=term))
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        organization = serializer.save(created_by=self.request.user)
        # The creator becomes the first admin.
        Membership.objects.create(
            organization=organization, user=self.request.user, role=Membership.Role.ADMIN
        )


class JoinRequestViewSet(viewsets.GenericViewSet):
    """Join requests for one organization (REQ-004). Any signed-in player can ask to join; only
    active admins of that organization can list or decide requests (TASK-013 replaces this check
    with real permissions). Routes are mapped explicitly in urls.py."""

    serializer_class = JoinRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    @extend_schema(responses={200: JoinRequestSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_admin(request.user, organization, "manage join requests")
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
            # Checked inside the transaction so a concurrently removed admin can't still decide.
            require_admin(request.user, organization, "manage join requests")
            join_request = get_object_or_404(
                JoinRequest.objects.select_for_update(), pk=pk, organization=organization
            )
            if join_request.status != JoinRequest.Status.PENDING:
                raise ApiException("already_decided", "This request has already been decided.", 409)
            join_request.status = outcome
            join_request.decided_at = timezone.now()
            join_request.decided_by = request.user
            join_request.save(update_fields=["status", "decided_at", "decided_by"])
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
    """Email invitations for one organization (REQ-004), admin only. Inviting an address never reveals
    whether it has an account or belongs to a member: the reply is the same and the email goes out
    either way (an existing member who accepts keeps their role)."""

    serializer_class = InvitationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    @property
    def throttle_scope(self):
        # Each invite sends an email, so sending is rate-limited per admin.
        return "invitations" if self.action == "create" else None

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    @extend_schema(responses={200: InvitationSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_admin(request.user, organization, "manage invitations")
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
            require_admin(request.user, organization, "manage invitations")
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
            require_admin(request.user, organization, "manage invitations")
            invitation = get_object_or_404(
                Invitation.objects.select_for_update(), pk=pk, organization=organization
            )
            if invitation.status != Invitation.Status.PENDING:
                raise ApiException("already_decided", "This invitation has already been answered.", 409)
            invitation.status = Invitation.Status.REVOKED
            invitation.decided_at = timezone.now()
            invitation.save(update_fields=["status", "decided_at"])
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
            invitation.status = outcome
            invitation.decided_at = timezone.now()
            if outcome == Invitation.Status.ACCEPTED:
                invitation.accepted_by = self.request.user
                join(invitation.organization, self.request.user)
                # An open join request to the same organization is moot now. It is withdrawn, not
                # approved, so the audit trail never shows a staff decision nobody made.
                JoinRequest.objects.filter(
                    organization=invitation.organization,
                    user=self.request.user,
                    status=JoinRequest.Status.PENDING,
                ).update(status=JoinRequest.Status.WITHDRAWN, decided_at=invitation.decided_at)
            invitation.save(update_fields=["status", "decided_at", "accepted_by"])
        return Response(MyInvitationSerializer(invitation).data)

    @extend_schema(request=None, responses={200: MyInvitationSerializer})
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._answer(pk, Invitation.Status.ACCEPTED)

    @extend_schema(request=None, responses={200: MyInvitationSerializer})
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._answer(pk, Invitation.Status.DECLINED)


class MyMembershipsView(generics.ListAPIView):
    """Organizations the signed-in player belongs to: the basis for the context switcher."""

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no user
            return Membership.objects.none()
        return Membership.objects.active().filter(user=self.request.user).select_related("organization")


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
