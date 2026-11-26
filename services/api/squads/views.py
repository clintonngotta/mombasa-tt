"""Representative squads (REQ-050).

Competition staff of a club or regional body manage squads under /organizations/{id}/squads/. A player
answers their own place under /me/squad-places/ and sees their own history there; nobody else's.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from notifications.models import Category
from notifications.service import notify
from organizations.access import require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from . import service
from .models import Squad, SquadPlace
from .serializers import (
    HistoryRowSerializer,
    MySquadPlaceSerializer,
    PickSerializer,
    PlaceAttendanceSerializer,
    SquadCandidateSerializer,
    SquadSerializer,
)

MANAGE = Permission.COMPETITIONS_MANAGE
MAX_SQUADS = 100
MAX_MY_PLACES = 100
SQUAD_KINDS = (
    Organization.Kind.CLUB,
    Organization.Kind.CLUB_FACILITY,
    Organization.Kind.REGIONAL_BODY,
)


def squads():
    return Squad.objects.select_related("organization").prefetch_related("places__user", "places__club")


def staff_organization(request, organization_pk) -> Organization:
    organization = get_object_or_404(Organization, pk=organization_pk)
    require_permission(request.user, organization, MANAGE)
    if organization.kind not in SQUAD_KINDS:
        raise ApiException("no_squads", "Clubs and regional bodies pick squads.", 404)
    return organization


def reply(squad: Squad, code=status.HTTP_200_OK) -> Response:
    return Response(SquadSerializer(squads().get(pk=squad.pk)).data, status=code)


def tell(place: SquadPlace, title: str) -> None:
    notify(
        [place.user_id],
        Category.SQUAD,
        title,
        subject=f"squad-place:{place.pk}",
        version=place.status,
        body=place.squad.title,
        link="/squads",
        organization=place.squad.organization,
    )


class SquadsView(APIView):
    """GET/POST /organizations/{org}/squads/: the organization's squads, latest first, for its
    competition staff. A new squad is a draft: nobody is told until it is published."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SquadSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        return Response(
            SquadSerializer(squads().filter(organization=organization)[:MAX_SQUADS], many=True).data
        )

    @extend_schema(request=SquadSerializer, responses={201: SquadSerializer})
    def post(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        body = SquadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        squad = Squad.objects.create(
            organization=organization, created_by=request.user, **body.validated_data
        )
        return reply(squad, status.HTTP_201_CREATED)


class SquadAction(APIView):
    permission_classes = [IsAuthenticated]

    def locked(self, request, organization_pk, pk) -> Squad:
        organization = staff_organization(request, organization_pk)
        return get_object_or_404(
            Squad.objects.select_for_update(of=("self",)).select_related("organization"),
            organization=organization,
            pk=pk,
        )


class SquadView(SquadAction):
    """GET/PATCH/DELETE /organizations/{org}/squads/{id}/. Only a draft is deleted. A slot that holds
    players can't be removed or made smaller than the players in it."""

    @extend_schema(responses={200: SquadSerializer})
    def get(self, request, organization_pk, pk):
        organization = staff_organization(request, organization_pk)
        return Response(SquadSerializer(get_object_or_404(squads(), organization=organization, pk=pk)).data)

    @extend_schema(request=SquadSerializer, responses={200: SquadSerializer})
    def patch(self, request, organization_pk, pk):
        with transaction.atomic():
            squad = self.locked(request, organization_pk, pk)
            body = SquadSerializer(squad, data=request.data, partial=True)
            body.is_valid(raise_exception=True)
            data = body.validated_data
            if "slots" in data:
                sizes = {slot["id"]: slot["places"] for slot in data["slots"]}
                held: dict = {}
                for slot_id in squad.places.filter(status__in=SquadPlace.OPEN).values_list("slot", flat=True):
                    held[slot_id] = held.get(slot_id, 0) + 1
                if any(sizes.get(slot_id, 0) < count for slot_id, count in held.items()):
                    raise ApiException("slot_in_use", "A slot can't be smaller than the players in it.", 409)
            for name, value in data.items():
                setattr(squad, name, value)
            squad.save()
        return reply(squad)

    @extend_schema(responses={204: None})
    def delete(self, request, organization_pk, pk):
        with transaction.atomic():
            squad = self.locked(request, organization_pk, pk)
            if squad.status != Squad.Status.DRAFT:
                raise ApiException("squad_published", "A published squad stays in the history.", 409)
            squad.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublishSquadView(SquadAction):
    """POST .../squads/{id}/publish/: tell everyone picked, who can then accept or decline."""

    @extend_schema(request=None, responses={200: SquadSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            squad = self.locked(request, organization_pk, pk)
            if squad.status == Squad.Status.DRAFT:
                squad.status = Squad.Status.PUBLISHED
                squad.published_at = timezone.now()
                squad.save(update_fields=["status", "published_at"])
                for place in squad.places.filter(status=SquadPlace.Status.PICKED).select_related(
                    "squad__organization"
                ):
                    tell(place, f"You're picked: {squad.title}")
        return reply(squad)


class RecommendationView(APIView):
    """GET .../squads/{id}/recommendation/: who can still be picked, in rotation: least recently
    represented first, then the higher rating; whoever was in the previous squad last."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SquadCandidateSerializer(many=True)})
    def get(self, request, organization_pk, pk):
        organization = staff_organization(request, organization_pk)
        squad = get_object_or_404(
            Squad.objects.select_related("organization"), organization=organization, pk=pk
        )
        return Response(SquadCandidateSerializer(service.recommendation(squad), many=True).data)


class PlacesView(SquadAction):
    """POST .../squads/{id}/places/: pick a player into a slot. Picking someone the rotation doesn't
    put next takes a reason, which is kept with the place."""

    @extend_schema(request=PickSerializer, responses={201: SquadSerializer})
    def post(self, request, organization_pk, pk):
        body = PickSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            squad = self.locked(request, organization_pk, pk)
            if squad.ends_on < timezone.localdate():
                raise ApiException("squad_over", "This tournament is over.", 409)
            place = service.pick(squad, request.user, **body.validated_data)
            if squad.status == Squad.Status.PUBLISHED:
                tell(place, f"You're picked: {squad.title}")
        return reply(squad, status.HTTP_201_CREATED)


class RemovePlaceView(SquadAction):
    """POST .../squads/{id}/places/{place}/remove/: take a player out of the squad. They are told."""

    @extend_schema(request=None, responses={200: SquadSerializer})
    def post(self, request, organization_pk, pk, place_pk):
        with transaction.atomic():
            squad = self.locked(request, organization_pk, pk)
            place = get_object_or_404(
                SquadPlace.objects.select_related("squad__organization"), squad=squad, pk=place_pk
            )
            if place.status in SquadPlace.OPEN:
                place.status = SquadPlace.Status.REMOVED
                place.responded_at = timezone.now()
                place.save(update_fields=["status", "responded_at"])
                if squad.status == Squad.Status.PUBLISHED:
                    tell(place, f"You're no longer in the squad: {squad.title}")
        return reply(squad)


class PlaceAttendanceView(SquadAction):
    """POST .../squads/{id}/places/{place}/attendance/: once the tournament has started, record whether
    a player who accepted went. The absence rules use it (REQ-054)."""

    @extend_schema(request=PlaceAttendanceSerializer, responses={200: SquadSerializer})
    def post(self, request, organization_pk, pk, place_pk):
        body = PlaceAttendanceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            squad = self.locked(request, organization_pk, pk)
            place = get_object_or_404(SquadPlace, squad=squad, pk=place_pk, status=SquadPlace.Status.ACCEPTED)
            if squad.status != Squad.Status.PUBLISHED or squad.starts_on > timezone.localdate():
                raise ApiException(
                    "squad_not_started", "Record who went once the tournament has started.", 409
                )
            place.attended = body.validated_data["attended"]
            place.save(update_fields=["attended"])
        return reply(squad)


class HistoryView(APIView):
    """GET /organizations/{org}/squads/history/: who has represented the organization, how often and
    when last, for its competition staff."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: HistoryRowSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        places = (
            SquadPlace.objects.filter(
                squad__organization=organization,
                squad__status=Squad.Status.PUBLISHED,
                status=SquadPlace.Status.ACCEPTED,
            )
            .select_related("user", "club", "squad")
            .order_by("-squad__starts_on")[:2000]
        )
        rows: dict = {}
        for place in places:
            row = rows.setdefault(
                place.user_id,
                {
                    "user_id": place.user_id,
                    "display_name": place.user.display_name,
                    "club": place.club.name if place.club else None,
                    "times": 0,
                    "last_represented_on": place.squad.starts_on,
                    "squads": [],
                },
            )
            row["times"] += 1
            if len(row["squads"]) < 10:
                row["squads"].append(place.squad.title)
        ordered = sorted(rows.values(), key=lambda row: (-row["times"], row["display_name"].lower()))
        return Response(HistoryRowSerializer(ordered, many=True).data)


# The player's own places -----------------------------------------------------------------------------


def mine(user):
    return (
        SquadPlace.objects.filter(user=user, squad__status=Squad.Status.PUBLISHED)
        .select_related("squad__organization")
        .prefetch_related("squad__places__user")
    )


class MySquadPlacesView(APIView):
    """GET /me/squad-places/: the squads you were picked for, latest first: those to answer, those you
    are in, and your history."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MySquadPlaceSerializer(many=True)})
    def get(self, request):
        found = mine(request.user).order_by("-squad__starts_on", "-picked_at")[:MAX_MY_PLACES]
        return Response(MySquadPlaceSerializer(found, many=True).data)


class AnswerPlaceView(APIView):
    """POST /me/squad-places/{id}/accept/ or /decline/: answer your place until the tournament starts.
    Declining frees the place for staff to fill."""

    permission_classes = [IsAuthenticated]
    answer = ""

    @extend_schema(request=None, responses={200: MySquadPlaceSerializer})
    def post(self, request, pk):
        with transaction.atomic():
            place = get_object_or_404(
                SquadPlace.objects.select_for_update(of=("self",)).select_related("squad__organization"),
                pk=pk,
                user=request.user,
                squad__status=Squad.Status.PUBLISHED,
            )
            if place.status not in SquadPlace.OPEN:
                raise ApiException("place_closed", "This place is no longer yours to answer.", 409)
            if place.squad.starts_on <= timezone.localdate():
                raise ApiException(
                    "squad_started", "The tournament has started. Speak to the organizers.", 409
                )
            place.status = self.answer
            place.responded_at = timezone.now()
            place.save(update_fields=["status", "responded_at"])
            if place.squad.created_by_id and place.squad.created_by_id != request.user.pk:
                word = "accepted" if self.answer == SquadPlace.Status.ACCEPTED else "declined"
                notify(
                    [place.squad.created_by_id],
                    Category.SQUAD,
                    f"{request.user.display_name} {word}: {place.squad.title}",
                    subject=f"squad-answer:{place.pk}",
                    version=self.answer,
                    link="/club/squads",
                    organization=place.squad.organization,
                )
        return Response(MySquadPlaceSerializer(mine(request.user).get(pk=place.pk)).data)
