import uuid

from django.db import transaction
from django.db.models import Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term
from organizations.access import effective_permissions, require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from . import lifecycle
from .models import MAX_EVENTS, Event, LifecycleEntry, Tournament
from .serializers import EventSerializer, LifecycleEntrySerializer, ReasonSerializer, TournamentSerializer

MANAGE = Permission.COMPETITIONS_MANAGE
T = Tournament.Status
E = Event.Status


def tournaments():
    return Tournament.objects.select_related("organization", "venue").prefetch_related("events")


def manages(user, organization: Organization) -> bool:
    return MANAGE in effective_permissions(user, organization)


def reply(tournament: Tournament, code=status.HTTP_200_OK) -> Response:
    return Response(TournamentSerializer(tournaments().get(pk=tournament.pk)).data, status=code)


def require_staff(user, tournament: Tournament) -> None:
    """A draft is 'not found' for anyone but the host's competition staff; a published one is theirs to
    read but staff-only beyond that."""
    if not manages(user, tournament.organization):
        if tournament.status == T.DRAFT:
            raise Http404
        raise ApiException("permission_denied", "Your role in this organization doesn't allow that.", 403)


def staff_tournament(user, pk) -> Tournament:
    """The tournament, locked for a change by someone who runs competitions for its host. A draft is
    'not found' for everyone else; a published one is theirs to read but not to change. Call inside a
    transaction."""
    tournament = get_object_or_404(
        Tournament.objects.select_for_update(of=("self",)).select_related("organization"), pk=pk
    )
    require_staff(user, tournament)
    return tournament


def ensure_open(tournament: Tournament) -> None:
    if tournament.is_closed:
        raise ApiException(
            "tournament_closed",
            f"This tournament is {tournament.get_status_display().lower()} and can't be changed.",
            409,
        )


class TournamentViewSet(viewsets.GenericViewSet):
    """Tournaments (REQ-007). Published tournaments are open to every signed-in player; drafts and all
    changes need competitions.manage in the host organization."""

    serializer_class = TournamentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Tournament, host or town"),
            OpenApiParameter("organization", str, description="Host organization id"),
            OpenApiParameter("when", str, enum=["upcoming", "past"]),
        ]
    )
    def list(self, request):
        """Published tournaments, drafts never. `when=upcoming` (soonest first) covers those still to
        finish; `when=past` (latest first) the completed, cancelled and ended ones."""
        found = tournaments().exclude(status=T.DRAFT)
        organization = request.query_params.get("organization")
        if organization:
            try:
                found = found.filter(organization_id=uuid.UUID(organization))
            except ValueError as error:
                raise ValidationError({"organization": "Not an organization id."}) from error
        term = search_term(request)
        if term:
            found = found.filter(
                Q(name__icontains=term)
                | Q(organization__name__icontains=term)
                | Q(venue__town__icontains=term)
            )
        when = request.query_params.get("when")
        today = timezone.localdate()
        over = Q(status__in=[T.COMPLETED, T.CANCELLED]) | Q(ends_on__lt=today, status=T.PUBLISHED)
        if when == "upcoming":
            found = found.exclude(over)
        elif when == "past":
            found = found.filter(over).order_by("-starts_on", "name", "id")
        page = self.paginate_queryset(found)
        return self.get_paginated_response(TournamentSerializer(page, many=True).data)

    def retrieve(self, request, pk):
        tournament = get_object_or_404(tournaments(), pk=pk)
        if tournament.status == T.DRAFT and not manages(request.user, tournament.organization):
            raise Http404
        return Response(TournamentSerializer(tournament).data)

    def partial_update(self, request, pk):
        with transaction.atomic():
            tournament = staff_tournament(request.user, pk)
            ensure_open(tournament)
            serializer = TournamentSerializer(
                tournament, data=request.data, partial=True, context={"organization": tournament.organization}
            )
            serializer.is_valid(raise_exception=True)
            zone = serializer.validated_data.get("timezone", tournament.timezone)
            if tournament.status == T.IN_PROGRESS and zone != tournament.timezone:
                raise ApiException(
                    "structure_frozen", "The timezone can't change once the tournament has started.", 409
                )
            changed = any(
                getattr(tournament, name) != value for name, value in serializer.validated_data.items()
            )
            serializer.save()
            # Once people can see it, every change to what was published is on the record.
            if changed and tournament.status != T.DRAFT:
                lifecycle.record(tournament, LifecycleEntry.Action.UPDATED, request.user)
        return reply(tournament)

    @extend_schema(responses={204: None})
    def destroy(self, request, pk):
        """Only a draft can be deleted; once published, a tournament is cancelled instead."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, pk)
            if tournament.status != T.DRAFT:
                raise ApiException(
                    "already_published", "A published tournament can't be deleted. Cancel it instead.", 409
                )
            tournament.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _transition(self, request, pk, change, **extra):
        with transaction.atomic():
            tournament = staff_tournament(request.user, pk)
            change(tournament, request.user, **extra)
        return reply(tournament)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def publish(self, request, pk):
        return self._transition(request, pk, lifecycle.publish)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def start(self, request, pk):
        return self._transition(request, pk, lifecycle.start)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def complete(self, request, pk):
        return self._transition(request, pk, lifecycle.complete)

    @extend_schema(request=ReasonSerializer, responses={200: TournamentSerializer})
    def cancel(self, request, pk):
        """Terminal and audited. The reason is shown to everyone who can see the tournament."""
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._transition(request, pk, lifecycle.cancel, reason=serializer.validated_data["reason"])

    @extend_schema(responses={200: LifecycleEntrySerializer(many=True)})
    def history(self, request, pk):
        """Who published, started, completed or cancelled what, and the configuration at that moment."""
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=pk)
        require_staff(request.user, tournament)
        entries = tournament.lifecycle.select_related("actor")
        return Response(LifecycleEntrySerializer(entries, many=True).data)


class OrganizationTournamentViewSet(viewsets.GenericViewSet):
    """Every tournament an organization hosts, drafts included, for its competition staff."""

    serializer_class = TournamentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_permission(request.user, organization, MANAGE)
        found = tournaments().filter(organization=organization).order_by("-starts_on", "name", "id")
        page = self.paginate_queryset(found)
        return self.get_paginated_response(TournamentSerializer(page, many=True).data)

    @extend_schema(request=TournamentSerializer, responses={201: TournamentSerializer})
    def create(self, request, organization_pk):
        """A new draft. The timezone defaults to the organization's."""
        organization = self.get_organization()
        require_permission(request.user, organization, MANAGE)
        serializer = TournamentSerializer(data=request.data, context={"organization": organization})
        serializer.is_valid(raise_exception=True)
        serializer.validated_data.setdefault("timezone", organization.timezone)
        tournament = serializer.save(organization=organization, created_by=request.user)
        return reply(tournament, status.HTTP_201_CREATED)


class EventViewSet(viewsets.GenericViewSet):
    """Events of one tournament (REQ-007), for the host's competition staff. Every reply is the whole
    tournament, so the caller always holds one consistent copy."""

    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated]

    def _event(self, tournament: Tournament, pk) -> Event:
        return get_object_or_404(Event, pk=pk, tournament=tournament)

    @extend_schema(request=EventSerializer, responses={201: TournamentSerializer})
    def create(self, request, tournament_pk):
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            ensure_open(tournament)
            serializer = EventSerializer(data=request.data, context={"tournament": tournament})
            serializer.is_valid(raise_exception=True)
            if tournament.events.count() >= MAX_EVENTS:
                raise ApiException("too_many_events", f"A tournament can have {MAX_EVENTS} events.", 409)
            last = tournament.events.aggregate(last=Max("position"))["last"]
            serializer.save(tournament=tournament, position=0 if last is None else last + 1)
        return reply(tournament, status.HTTP_201_CREATED)

    @extend_schema(request=EventSerializer, responses={200: TournamentSerializer})
    def partial_update(self, request, tournament_pk, pk):
        """Change an event's set-up. Once it has started its structure (type, format, best of, seeding,
        groups and qualifiers) is frozen: asking to change it is a 409, never a silent no-op."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            ensure_open(tournament)
            event = self._event(tournament, pk)
            if event.is_closed:
                raise ApiException(
                    "event_closed",
                    f"This event is {event.get_status_display().lower()} and can't be changed.",
                    409,
                )
            serializer = EventSerializer(event, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            changed = {
                name for name, value in serializer.validated_data.items() if getattr(event, name) != value
            }
            if event.status != E.SCHEDULED and serializer.structure_changes:
                raise ApiException(
                    "structure_frozen",
                    "This event has started, so its format, best of, seeding, groups and qualifiers "
                    "can't change.",
                    409,
                )
            if changed:
                serializer.save(revision=event.revision + 1)
        return reply(tournament)

    @extend_schema(responses={200: TournamentSerializer})
    def destroy(self, request, tournament_pk, pk):
        """Only while the tournament is a draft; afterwards an event is cancelled, which keeps a record."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            event = self._event(tournament, pk)
            if tournament.status != T.DRAFT:
                raise ApiException(
                    "already_published",
                    "Events of a published tournament can't be deleted. Cancel the event instead.",
                    409,
                )
            lifecycle.record(tournament, LifecycleEntry.Action.EVENT_REMOVED, request.user, event=event)
            event.delete()
        return reply(tournament)

    def _transition(self, request, tournament_pk, pk, change, **extra):
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            ensure_open(tournament)
            change(tournament, self._event(tournament, pk), request.user, **extra)
        return reply(tournament)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def start(self, request, tournament_pk, pk):
        return self._transition(request, tournament_pk, pk, lifecycle.start_event)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def complete(self, request, tournament_pk, pk):
        return self._transition(request, tournament_pk, pk, lifecycle.complete_event)

    @extend_schema(request=ReasonSerializer, responses={200: TournamentSerializer})
    def cancel(self, request, tournament_pk, pk):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._transition(
            request, tournament_pk, pk, lifecycle.cancel_event, reason=serializer.validated_data["reason"]
        )
