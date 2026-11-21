from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from attachments.images import MAX_UPLOAD_BYTES, OUTPUT_CONTENT_TYPE, normalize_image
from attachments.models import Attachment
from core.pagination import StandardPagination, search_term
from core.permissions import PublicReads
from organizations.models import Membership
from ratings.models import RatingEvent

from .models import PlayerProfile, listed_profiles, profile_for
from .serializers import (
    AvatarUploadSerializer,
    DirectoryPlayerSerializer,
    GoalsSerializer,
    PlayerSerializer,
    ProfileSerializer,
    SignedOutPlayerSerializer,
)

MIN_SEARCH_LENGTH = 2
AVATAR_SIDE = 512
MULTIPART_OVERHEAD = 64 * 1024  # form boundaries and headers around the file


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return profile_for(self.request.user)


class AvatarView(APIView):
    """The player's own picture (REQ-006). Stored privately; others get it only through the directory."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_scope = "uploads"

    def _replace(self, user, content: bytes | None) -> PlayerProfile:
        """Swap the player's photo for `content` (None removes it) and delete the old one."""
        new = None
        try:
            with transaction.atomic():
                profile = PlayerProfile.objects.select_for_update().get(pk=profile_for(user).pk)
                old = profile.avatar
                if content is not None:
                    new = Attachment.store(
                        owner=user,
                        purpose=Attachment.Purpose.AVATAR,
                        content=content,
                        content_type=OUTPUT_CONTENT_TYPE,
                    )
                profile.avatar = new
                profile.save(update_fields=["avatar", "updated_at"])
                if old:
                    old.delete()
        except BaseException:
            if new is not None:
                new.discard_file()  # its row was rolled back; don't leave the file behind
            raise
        return profile

    @extend_schema(
        request={"multipart/form-data": AvatarUploadSerializer}, responses={200: ProfileSerializer}
    )
    def put(self, request):
        # Refuse an oversized body before reading it (the proxy caps it too, see deployment.md).
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD:
            raise ValidationError({"file": "Choose an image under 5 MB."})
        serializer = AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = normalize_image(serializer.validated_data["file"], max_side=AVATAR_SIDE)
        return Response(ProfileSerializer(self._replace(request.user, content)).data)

    @extend_schema(request=None, responses={204: None})
    def delete(self, request):
        self._replace(request.user, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=GoalsSerializer, responses={200: GoalsSerializer})
    def put(self, request):
        serializer = GoalsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = profile_for(request.user)
        profile.goals = serializer.validated_data["goals"]
        profile.save(update_fields=["goals", "updated_at"])
        return Response({"goals": profile.goals})


class CompleteOnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        profile = profile_for(request.user)
        if profile.onboarding_completed_at is None:  # repeat calls keep the first completion time
            profile.onboarding_completed_at = timezone.now()
            profile.save(update_fields=["onboarding_completed_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def listed_players():
    """Profiles that may be shown to other players: opted in and active (REQ-006)."""
    active = Membership.objects.active().select_related("organization")
    return (
        listed_profiles()
        .select_related("user")
        .prefetch_related(Prefetch("user__memberships", queryset=active))
    )


class PlayerDirectoryView(generics.ListAPIView):
    """Opted-in players only (REQ-006). Searching needs at least two characters so the
    directory can't be dumped with an empty query."""

    serializer_class = DirectoryPlayerSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    @extend_schema(parameters=[OpenApiParameter("search", str, description="Name or nickname")])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        term = search_term(self.request)
        if len(term) < MIN_SEARCH_LENGTH:
            return PlayerProfile.objects.none()
        return (
            listed_players()
            .filter(Q(user__display_name__icontains=term) | Q(nickname__icontains=term))
            .order_by("user__display_name")
        )


class PlayerDetailView(generics.RetrieveAPIView):
    """One listed player's page. 404 once they opt out, so opting out removes the page too.

    Signed out (TASK-035) the directory doesn't apply: the page is there only for a listed player with
    competition records, and carries their name alone, as their public ratings page does. No photo,
    nickname, clubs or published details."""

    serializer_class = PlayerSerializer
    permission_classes = [PublicReads]
    public_actions = ("get",)  # held to the visitors' allowance (core/throttling.py)

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return listed_players()
        competed = RatingEvent.objects.filter(user_id=OuterRef("user_id"))
        return listed_profiles().select_related("user").filter(Exists(competed))

    @extend_schema(responses=PlayerSerializer)  # one shape either way: signed out, most fields are blank
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_serializer_class(self):
        return PlayerSerializer if self.request.user.is_authenticated else SignedOutPlayerSerializer
