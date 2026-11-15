from django.db.models import Prefetch, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import Membership

from .models import PlayerProfile, profile_for
from .serializers import DirectoryPlayerSerializer, GoalsSerializer, ProfileSerializer

MIN_SEARCH_LENGTH = 2


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return profile_for(self.request.user)


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


class DirectoryPagination(PageNumberPagination):
    page_size = 20


class PlayerDirectoryView(generics.ListAPIView):
    """Opted-in players only (REQ-006). Searching needs at least two characters so the
    directory can't be dumped with an empty query."""

    serializer_class = DirectoryPlayerSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = DirectoryPagination

    @extend_schema(parameters=[OpenApiParameter("search", str, description="Name or nickname")])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        term = self.request.query_params.get("search", "").strip()
        if len(term) < MIN_SEARCH_LENGTH:
            return PlayerProfile.objects.none()
        active = Membership.objects.filter(status=Membership.Status.ACTIVE).select_related("organization")
        return (
            PlayerProfile.objects.filter(directory_opt_in=True, user__is_active=True)
            .filter(Q(user__display_name__icontains=term) | Q(nickname__icontains=term))
            .select_related("user")
            .prefetch_related(Prefetch("user__memberships", queryset=active))
            .order_by("user__display_name")
        )
