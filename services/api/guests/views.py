"""Guests (REQ-003): club staff create and invite them; the invitee claims; staff resolve clashes."""

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term
from organizations.access import require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from . import service
from .models import Guest, GuestClaim, GuestClaimEvent, GuestInvitation
from .serializers import (
    ClaimNoteSerializer,
    GuestClaimSerializer,
    GuestInviteSerializer,
    GuestSerializer,
    GuestWriteSerializer,
    MyClaimSerializer,
    MyGuestInvitationSerializer,
)

# Staff who enter players or look after members look after guests too.
GUEST_STAFF = (Permission.COMPETITIONS_MANAGE, Permission.MEMBERS_MANAGE)


class _ClubScoped:
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def organization(self) -> Organization:
        if hasattr(self, "_organization"):
            return self._organization
        organization = get_object_or_404(Organization, pk=self.kwargs["organization_pk"])
        require_permission(self.request.user, organization, *GUEST_STAFF)
        self._organization = organization
        return organization


class GuestViewSet(_ClubScoped, viewsets.GenericViewSet):
    """A club's guests: players its staff entered before they had an account."""

    serializer_class = GuestSerializer
    lookup_field = "user_id"
    lookup_url_kwarg = "pk"  # the player's id

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Guest.objects.none()
        return (
            Guest.objects.filter(organization=self.organization())
            .select_related("user", "claimed_by")
            .prefetch_related(
                Prefetch("invitations", queryset=GuestInvitation.objects.filter(status="pending"))
            )
            .annotate(entries=Count("user__entry_places", filter=Q(user__entry_places__live=True)))
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Part of the guest's name."),
            OpenApiParameter("claimed", bool, description="Only claimed (true) or unclaimed (false) guests."),
        ]
    )
    def list(self, request, organization_pk):
        guests = self.get_queryset()
        if term := search_term(request):
            guests = guests.filter(user__display_name__icontains=term)
        claimed = request.query_params.get("claimed")
        if claimed in {"true", "false"}:
            guests = guests.filter(claimed_by__isnull=claimed == "false")
        page = self.paginate_queryset(guests)
        return self.get_paginated_response(GuestSerializer(page, many=True).data)

    @extend_schema(request=GuestWriteSerializer, responses={201: GuestSerializer})
    def create(self, request, organization_pk):
        organization = self.organization()
        body = GuestWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        guest = service.create(organization, body.validated_data["display_name"], request.user)
        return Response(
            GuestSerializer(self.get_queryset().get(pk=guest.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=GuestWriteSerializer, responses={200: GuestSerializer})
    def partial_update(self, request, organization_pk, pk):
        body = GuestWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            guest = self._locked(pk)
            service.still_a_guest(guest)
            guest.user.display_name = body.validated_data["display_name"]
            guest.user.save(update_fields=["display_name"])
        return Response(GuestSerializer(self.get_queryset().get(pk=guest.pk)).data)

    def _locked(self, user_id) -> Guest:
        """The guest, locked against a concurrent invite, claim or rename."""
        return get_object_or_404(
            Guest.objects.select_for_update().select_related("user", "organization"),
            organization=self.organization(),
            user_id=user_id,
        )

    @extend_schema(request=GuestInviteSerializer, responses={201: GuestSerializer})
    @action(detail=True, methods=["post"])
    def invite(self, request, organization_pk, pk):
        body = GuestInviteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            guest = self._locked(pk)
            service.invite(guest, body.validated_data["email"], request.user)
        return Response(
            GuestSerializer(self.get_queryset().get(pk=guest.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=None, responses={200: GuestSerializer})
    @action(detail=True, methods=["post"], url_path="revoke-invitation")
    def revoke_invitation(self, request, organization_pk, pk):
        with transaction.atomic():
            guest = self._locked(pk)
            invitation = guest.invitations.filter(status=GuestInvitation.Status.PENDING).first()
            if invitation is None:
                raise ApiException("no_invitation", "This guest has no open invitation.", 409)
            service.revoke(invitation)
        return Response(GuestSerializer(self.get_queryset().get(pk=guest.pk)).data)


class GuestClaimViewSet(_ClubScoped, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Claims of a club's guests, with their audit trail. A claim in `conflict` waits for staff."""

    serializer_class = GuestClaimSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GuestClaim.objects.none()
        claims = (
            GuestClaim.objects.filter(guest__organization=self.organization())
            .select_related("guest__user", "claimant", "invitation")
            .prefetch_related(Prefetch("events", queryset=GuestClaimEvent.objects.select_related("actor")))
        )
        wanted = self.request.query_params.get("status")
        return claims.filter(status=wanted) if wanted in GuestClaim.Status.values else claims

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=GuestClaim.Status.values, description="Only these.")]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _settle(self, request, pk, do):
        body = ClaimNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            claim = get_object_or_404(self.get_queryset().select_for_update(of=("self",)), pk=pk)
            do(claim, request.user, body.validated_data["note"])
        return Response(GuestClaimSerializer(self.get_queryset().get(pk=claim.pk)).data)

    @extend_schema(request=ClaimNoteSerializer, responses={200: GuestClaimSerializer})
    @action(detail=True, methods=["post"])
    def retry(self, request, organization_pk, pk=None):
        return self._settle(request, pk, service.retry)

    @extend_schema(request=ClaimNoteSerializer, responses={200: GuestClaimSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request, organization_pk, pk=None):
        return self._settle(request, pk, service.reject)


class MyGuestInvitationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Open guest invitations to the signed-in player's verified address."""

    serializer_class = MyGuestInvitationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GuestInvitation.objects.none()
        user = self.request.user
        if not user.email_verified_at:  # an unverified address proves nothing about who owns it
            return GuestInvitation.objects.none()
        return GuestInvitation.objects.filter(
            email__iexact=user.email, status=GuestInvitation.Status.PENDING, expires_at__gt=timezone.now()
        ).select_related("guest__user", "guest__organization", "invited_by")

    @extend_schema(request=None, responses={200: MyClaimSerializer})
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        with transaction.atomic():
            invitation = get_object_or_404(self.get_queryset().select_for_update(of=("self",)), pk=pk)
            Guest.objects.select_for_update().get(pk=invitation.guest_id)
            claim = service.accept(invitation, request.user)
        return Response(MyClaimSerializer(claim).data)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        with transaction.atomic():
            invitation = get_object_or_404(self.get_queryset().select_for_update(of=("self",)), pk=pk)
            service.decline(invitation)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyGuestClaimViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The signed-in player's claims and how each ended."""

    serializer_class = MyClaimSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GuestClaim.objects.none()
        return GuestClaim.objects.filter(claimant=self.request.user).select_related(
            "guest__user", "guest__organization"
        )
