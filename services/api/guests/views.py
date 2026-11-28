"""Guests (REQ-003): club staff create and invite them; the invitee claims; staff resolve clashes."""

from django.contrib.auth import login
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from competitions.models import EntryPlayer
from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term
from organizations.access import require_permission
from organizations.models import Membership, Organization
from organizations.permissions import Permission
from profiles.models import listed_profiles

from . import service
from .models import Guest, GuestClaim, GuestClaimEvent, GuestInvitation
from .serializers import (
    ClaimNoteSerializer,
    GuestClaimSerializer,
    GuestCreateSerializer,
    GuestInviteSerializer,
    GuestLinkPlayerSerializer,
    GuestSerializer,
    GuestWriteSerializer,
    InvitationDetailSerializer,
    InvitationJoinedSerializer,
    InvitationJoinSerializer,
    InvitedGuestSerializer,
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
                Prefetch(
                    "invitations",
                    queryset=GuestInvitation.objects.filter(status="pending").select_related("invitee"),
                )
            )
            .annotate(entries=Count("user__entry_places", filter=Q(user__entry_places__live=True)))
            .order_by("user__display_name", "created_at", "pk")  # an aggregate drops Meta.ordering
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

    def _invited(self, guest: Guest, token: str | None) -> dict:
        data = InvitedGuestSerializer(self.get_queryset().get(pk=guest.pk)).data
        data["invite_link"] = service.join_link(token) if token else None
        return data

    @extend_schema(request=GuestCreateSerializer, responses={201: InvitedGuestSerializer})
    def create(self, request, organization_pk):
        """A new guest. With an email or phone they are invited at once, and `invite_link` is the link
        to share with them (shown this once)."""
        organization = self.organization()
        body = GuestCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        token = None
        with transaction.atomic():
            guest = service.create(organization, data["display_name"], request.user)
            if data.get("email") or data.get("phone"):
                _, token = service.invite(guest, data.get("email"), request.user, data.get("phone") or "")
        return Response(self._invited(guest, token), status=status.HTTP_201_CREATED)

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

    @extend_schema(request=GuestInviteSerializer, responses={201: InvitedGuestSerializer})
    @action(detail=True, methods=["post"])
    def invite(self, request, organization_pk, pk):
        """Invite by email (we send the link), phone (share `invite_link` yourself) or both."""
        body = GuestInviteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        with transaction.atomic():
            guest = self._locked(pk)
            _, token = service.invite(guest, data.get("email"), request.user, data.get("phone") or "")
        return Response(self._invited(guest, token), status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={201: InvitedGuestSerializer})
    @action(detail=True, methods=["post"], url_path="new-link")
    def new_link(self, request, organization_pk, pk):
        """A fresh invitation link to share, to the email and phone last invited (if any); nothing is
        emailed. The old link stops working. `invite_link` is shown this once."""
        with transaction.atomic():
            guest = self._locked(pk)
            _, token = service.new_link(guest, request.user)
        return Response(self._invited(guest, token), status=status.HTTP_201_CREATED)

    @extend_schema(request=GuestLinkPlayerSerializer, responses={201: GuestSerializer})
    @action(detail=True, methods=["post"], url_path="link-player")
    def link_player(self, request, organization_pk, pk):
        """Ask a player found in the player directory whether they are this guest. They accept or
        decline in the app; nothing moves until they accept."""
        body = GuestLinkPlayerSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            guest = self._locked(pk)
            # Only players who chose to be found in the directory, as the search that found them.
            profile = (
                listed_profiles()
                .filter(user_id=body.validated_data["player_id"])
                .select_related("user")
                .first()
            )
            if profile is None:
                raise ValidationError({"player_id": "Choose a player from the search."})
            service.link_player(guest, profile.user, request.user)
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
            .select_related("guest__user", "claimant", "invitation__invitee")
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
    """Guest invitations waiting for the signed-in player: those addressed to them as a player found in
    the directory, while open, and those to their verified email. An email one stays here after its link
    has lapsed, so a player who joins on their own later still finds what they played as a guest. Names
    are never matched."""

    serializer_class = MyGuestInvitationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GuestInvitation.objects.none()
        user = self.request.user
        mine = Q(invitee=user, expires_at__gt=timezone.now())
        if user.email and user.email_verified_at:  # an unverified address proves nothing about who owns it
            mine |= Q(email__iexact=user.email, invitee__isnull=True)
        return (
            GuestInvitation.objects.filter(
                mine, status=GuestInvitation.Status.PENDING, guest__claimed_by__isnull=True
            )
            .exclude(guest__user=user)
            .select_related("guest__user", "guest__organization", "invited_by")
        )

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


def _gone():
    return ApiException(
        "invitation_closed", "This invitation link has been used, withdrawn or has expired.", 404
    )


@method_decorator(csrf_protect, name="dispatch")
class JoinInvitationView(APIView):
    """An invitation link (`/join/<token>`), open to whoever holds it: the link is the proof."""

    permission_classes = [AllowAny]
    throttle_scope = "auth_email"

    def get_throttles(self):
        # Reading the link is cheap and harmless; creating an account is rate limited.
        return super().get_throttles() if self.request.method == "POST" else []

    @extend_schema(responses={200: InvitationDetailSerializer})
    def get(self, request, token):
        invitation = service.by_token(token)
        if invitation is None:
            raise _gone()
        guest = invitation.guest
        places = (
            EntryPlayer.objects.filter(user_id=guest.user_id, live=True)
            .select_related("event__tournament")
            .order_by("event__tournament__starts_on", "event__name")
        )
        return Response(
            InvitationDetailSerializer(
                {
                    "guest_name": guest.user.display_name,
                    "organization_name": guest.organization.name,
                    "invited_by_name": invitation.invited_by.display_name if invitation.invited_by else None,
                    "email": invitation.email,
                    "phone": invitation.phone,
                    "expires_at": invitation.expires_at,
                    "is_member": Membership.objects.active()
                    .filter(organization_id=guest.organization_id, user_id=guest.user_id)
                    .exists(),
                    "entries": [
                        {
                            "tournament_id": place.event.tournament_id,
                            "tournament_name": place.event.tournament.name,
                            "event_name": place.event.name,
                            "starts_on": place.event.tournament.starts_on,
                        }
                        for place in places
                    ],
                }
            ).data
        )

    @extend_schema(request=InvitationJoinSerializer, responses={200: InvitationJoinedSerializer})
    def post(self, request, token):
        """Create the invitee's account from the guest. Signed in at once when the email or phone they
        chose is the one the invitation went to; otherwise their email needs verifying first."""
        body = InvitationJoinSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            invitation = service.by_token(token, lock=True)
            if invitation is None:
                raise _gone()
            Guest.objects.select_for_update().get(pk=invitation.guest_id)
            try:
                user, ready = service.join(invitation, body.validated_data)
            except service.Taken as taken:
                # Only someone holding the link learns this, and they are the one it was meant for.
                raise ApiException(
                    f"{taken.field}_taken",
                    f"That {'email address' if taken.field == 'email' else 'phone number'} already has an "
                    "account. Log in with it, then open this link again to add these entries to it.",
                    409,
                ) from None
        if ready:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(InvitationJoinedSerializer({"signed_in": ready}).data)


class ClaimByLinkView(APIView):
    """A signed-in player with an invitation link claims the guest for their own account."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: MyClaimSerializer})
    def post(self, request, token):
        with transaction.atomic():
            invitation = service.by_token(token, lock=True)
            if invitation is None:
                raise _gone()
            Guest.objects.select_for_update().get(pk=invitation.guest_id)
            claim = service.accept(invitation, request.user)
        return Response(MyClaimSerializer(claim).data)
