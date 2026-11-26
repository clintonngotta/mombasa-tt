"""A tournament's review (REQ-055): what went well, what went wrong and actions for next time.

The host's competition staff write it once the tournament is over. They and the officials whose
jurisdiction covers the host read it; nobody else learns whether one exists.
"""

from zoneinfo import ZoneInfo

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from organizations.access import official_for

from .models import Tournament, TournamentReview
from .views import manages, staff_tournament

MAX_ACTIONS = 30


class ReviewActionSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=300, trim_whitespace=True)
    owner = serializers.CharField(
        max_length=120,
        trim_whitespace=True,
        allow_blank=True,
        required=False,
        default="",
        help_text="Who will do it, as a name: they may not have an account.",
    )
    due_on = serializers.DateField(required=False, allow_null=True, default=None)
    done = serializers.BooleanField(required=False, default=False)


class TournamentReviewSerializer(serializers.Serializer):
    """The review. Before one is written every field is empty and `updated_at` is null."""

    went_well = serializers.CharField(
        max_length=5000, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    went_wrong = serializers.CharField(
        max_length=5000, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    actions = ReviewActionSerializer(many=True, required=False, max_length=MAX_ACTIONS)
    updated_by_name = serializers.CharField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    can_edit = serializers.BooleanField(
        read_only=True, help_text="You run competitions for the host and the tournament is over."
    )

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        if not (attrs.get("went_well") or attrs.get("went_wrong") or attrs.get("actions")):
            raise serializers.ValidationError(
                {"went_well": "Write what went well, what went wrong or an action."}
            )
        return attrs


def is_over(tournament: Tournament) -> bool:
    """Completed, or its last day has come (in its own timezone)."""
    today = timezone.localdate(timezone=ZoneInfo(tournament.timezone))
    return tournament.status == Tournament.Status.COMPLETED or (
        tournament.status != Tournament.Status.DRAFT and tournament.ends_on <= today
    )


def shown(tournament: Tournament, user) -> dict:
    review = TournamentReview.objects.filter(tournament=tournament).select_related("updated_by").first()
    staff = manages(user, tournament.organization)
    return {
        "went_well": review.went_well if review else "",
        "went_wrong": review.went_wrong if review else "",
        "actions": review.actions if review else [],
        "updated_by_name": review.updated_by.display_name if review and review.updated_by else None,
        "updated_at": review.updated_at if review else None,
        "can_edit": staff and is_over(tournament),
    }


class TournamentReviewView(APIView):
    """GET /tournaments/{id}/review/: the review, for the host's competition staff and the officials of
    its region and country. PUT writes it: the host's competition staff, once the tournament is over."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: TournamentReviewSerializer})
    def get(self, request, tournament_pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        host = tournament.organization
        if not (manages(request.user, host) or official_for(request.user, host)):
            # Nobody else learns that a tournament has a review, or that a draft exists.
            if tournament.status == Tournament.Status.DRAFT:
                raise Http404
            raise ApiException("permission_denied", "The review is for the host's staff and officials.", 403)
        return Response(TournamentReviewSerializer(shown(tournament, request.user)).data)

    @extend_schema(request=TournamentReviewSerializer, responses={200: TournamentReviewSerializer})
    def put(self, request, tournament_pk):
        body = TournamentReviewSerializer(data=request.data)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            body.is_valid(raise_exception=True)
            if not is_over(tournament):
                raise ApiException(
                    "tournament_not_over", "Write the review once the tournament is over.", 409
                )
            data = body.validated_data
            actions = [
                {**row, "due_on": row["due_on"].isoformat() if row.get("due_on") else None}
                for row in data.get("actions", [])
            ]
            TournamentReview.objects.update_or_create(
                tournament=tournament,
                defaults={
                    "went_well": data["went_well"],
                    "went_wrong": data["went_wrong"],
                    "actions": actions,
                    "updated_by": request.user,
                },
            )
        return Response(TournamentReviewSerializer(shown(tournament, request.user)).data)
