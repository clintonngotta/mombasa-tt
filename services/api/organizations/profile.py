"""What a signed-in player sees of a club before joining: where it is, what it is about, when it trains and
its coming tournaments. Members, roles, training plans, drills and finances stay behind membership."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from competitions.models import Tournament
from core.geography import coordinate_field
from facilities.serializers import TrainingHourSerializer, VenueSummarySerializer

from .models import Organization

UPCOMING_LIMIT = 10


class UpcomingTournamentSerializer(serializers.ModelSerializer):
    venue_name = serializers.CharField(source="venue.name", read_only=True, default=None)

    class Meta:
        model = Tournament
        fields = ["id", "name", "starts_on", "ends_on", "scope", "status", "venue_name"]
        read_only_fields = fields


class ClubProfileSerializer(serializers.ModelSerializer):
    latitude = coordinate_field(90)
    longitude = coordinate_field(180)
    venues = serializers.SerializerMethodField()
    training_hours = serializers.SerializerMethodField()
    upcoming_tournaments = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "kind", "country", "region", "town", "directions", "latitude", "longitude"]
        fields += ["description", "timezone", "venues", "training_hours", "upcoming_tournaments"]
        read_only_fields = fields

    @extend_schema_field(VenueSummarySerializer(many=True))
    def get_venues(self, organization):
        return VenueSummarySerializer(organization.venues.filter(active=True), many=True).data

    @extend_schema_field(TrainingHourSerializer(many=True))
    def get_training_hours(self, organization):
        hours = organization.training_hours.select_related("venue")
        return TrainingHourSerializer(hours, many=True, context={"organization": organization}).data

    @extend_schema_field(UpcomingTournamentSerializer(many=True))
    def get_upcoming_tournaments(self, organization):
        # "Upcoming" by the club's own calendar: a tournament that ends today is still on.
        today = datetime.now(ZoneInfo(organization.timezone)).date()
        T = Tournament.Status
        tournaments = (
            organization.tournaments.filter(status__in=[T.PUBLISHED, T.IN_PROGRESS], ends_on__gte=today)
            .select_related("venue")
            .order_by("starts_on", "name")[:UPCOMING_LIMIT]
        )
        return UpcomingTournamentSerializer(tournaments, many=True).data


class ClubProfileView(APIView):
    """GET /organizations/{id}/profile/: any signed-in player, member or not."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ClubProfileSerializer})
    def get(self, request, pk):
        organization = get_object_or_404(Organization, pk=pk)
        return Response(ClubProfileSerializer(organization).data)
