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
from rest_framework.views import APIView

from accounts.models import VERIFIED, User
from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term
from core.permissions import PublicReads, is_platform_super_admin
from organizations.access import (
    effective_permissions,
    jurisdiction,
    managed_organizations,
    require_permission,
)
from organizations.models import BODY_KINDS, Membership, Organization
from organizations.permissions import Permission

from . import drawing, entries, lifecycle, matchday, official, player_record, substitutes, ties
from .emails import send_entry_news
from .models import MAX_EVENTS, SLUG_MAX_LENGTH, DrawVersion, Entry, Event, LifecycleEntry, Match, Tournament
from .serializers import (
    DrawMoveSerializer,
    DrawRequestSerializer,
    EntryRequestSerializer,
    EntrySerializer,
    EventDrawSerializer,
    EventSerializer,
    LifecycleEntrySerializer,
    LineupRequestSerializer,
    MatchDetailSerializer,
    MyEntrySerializer,
    OptionalReasonSerializer,
    ReasonSerializer,
    StandingsSerializer,
    SubstituteSerializer,
    TournamentPlayerSerializer,
    TournamentSerializer,
)

MANAGE = Permission.COMPETITIONS_MANAGE
MAX_SEARCH = 100
T = Tournament.Status
E = Event.Status


def tournaments():
    return Tournament.objects.detailed()


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


def approver_tournament(user, pk) -> Tournament:
    """The tournament, locked, for its host's competition staff or for somebody who approves its tier
    (a platform super admin or the responsible official). Call inside a transaction."""
    tournament = get_object_or_404(
        Tournament.objects.select_for_update(of=("self",)).select_related("organization"), pk=pk
    )
    if not approves(user, tournament):
        require_staff(user, tournament)
    return tournament


def approves(user, tournament: Tournament) -> bool:
    """Whoever approves the tier of a regional, national or international tournament, once its host has
    asked for approval (or it is already out)."""
    if tournament.scope == Tournament.Scope.LOCAL or not lifecycle.can_approve(tournament, user):
        return False
    return tournament.status != T.DRAFT or tournament.approval_status != Tournament.Approval.NOT_REQUESTED


def sees_draft(user, tournament: Tournament) -> bool:
    """A draft is shown to its host's competition staff, and to whoever approves its tier once the host
    asks for approval."""
    return manages(user, tournament.organization) or approves(user, tournament)


def sees_tournament(user, attachment) -> bool:
    """Whether `user` may see the tournament that `attachment` (a cover or document) belongs to."""
    tournament = (
        Tournament.objects.filter(Q(cover=attachment) | Q(documents__file=attachment))
        .select_related("organization")
        .first()
    )
    if tournament is None:
        return False
    return tournament.status != T.DRAFT or sees_draft(user, tournament)


def ensure_open(tournament: Tournament) -> None:
    if tournament.is_closed:
        raise ApiException(
            "tournament_closed",
            f"This tournament is {tournament.get_status_display().lower()} and can't be changed.",
            409,
        )


def match_reply(request, draw: DrawVersion | None, pk) -> Response:
    """One match of `draw` as MatchDetailSerializer shows it to the caller: its tie if it is one, and
    where its scoring stands."""
    from reservations import service as reservations  # both build on competitions
    from reservations.models import Reservation
    from scoring import service as scoring

    staff = bool(draw) and manages(request.user, draw.event.tournament.organization)
    shown = drawing.describe_match(draw, pk, staff) if draw else None
    if shown is None:
        raise Http404
    match = shown.pop("match")
    if draw.event.is_team:
        shown["tie"] = ties.describe(match, request.user, staff)
        shown["scoring"] = None
        by_id = {rubber.id: rubber for rubber in match.rubbers.all()}
        for rubber in shown["tie"]["rubbers"]:
            rubber["scoring"] = scoring.summary(match, by_id[rubber["id"]], request.user, staff)
    else:
        shown["tie"] = None
        shown["scoring"] = scoring.summary(match, None, request.user, staff)
    shown["can_dispatch"] = staff and reservations.is_dispatchable(match)
    versions = official.history(match)
    standing = next((v for v in versions if v["current"] and v["rubber"] is None), None)
    if standing and not staff:
        # Who recorded a result and why it was corrected is the organizers' record, not the public's.
        standing = {**standing, "reason": "", "recorded_by": ""}
    shown["result"] = standing
    shown["result_history"] = versions if staff else []
    closed = draw.event.is_closed or draw.event.tournament.is_closed
    # The host's referee records results too, and only the referee awards or changes a walkover or a
    # disqualification (D5, REQ-043).
    referee = Permission.RESULTS_REFEREE in effective_permissions(
        request.user, draw.event.tournament.organization
    )
    referees_only = (Match.Outcome.WALKOVER, Match.Outcome.DISQUALIFIED)
    referee_decided = standing is not None and standing["outcome"] in referees_only
    # Nobody records or changes the result of a match they play in.
    may_record = (referee or (staff and not referee_decided)) and not official.plays_in(match, request.user)
    shown["can_record_result"] = may_record and not closed and draw.status == DrawVersion.Status.PUBLISHED
    shown["can_award_walkover"] = shown["can_record_result"] and referee
    shown["held_for_correction"] = match.resolutions.filter(resolved_at__isnull=True).exists()
    held = (
        match.reservations.filter(status=Reservation.Status.ACTIVE)
        .select_related("table")
        .prefetch_related("holds__user")
    )
    shown["on_table"] = (
        {
            "table": held[0].table.label,
            "since": held[0].created_at,
            "people": sorted(h.user.display_name for h in held[0].holds.all() if h.user_id and h.active),
            # A tie holds its players rubber by rubber: say who couldn't be held for the current one.
            "waiting_for": [u.display_name for u in reservations.missing_people(held[0])] if staff else [],
        }
        if held
        else None
    )
    return Response(MatchDetailSerializer(shown, context={"request": request}).data)


class TournamentViewSet(viewsets.GenericViewSet):
    """Tournaments (REQ-007). Published tournaments are open to every signed-in player; drafts and all
    changes need competitions.manage in the host organization."""

    serializer_class = TournamentSerializer
    permission_classes = [PublicReads]
    public_actions = ("list", "retrieve", "by_slug")  # published tournaments are public (TASK-035)
    pagination_class = StandardPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Tournament, host or town"),
            OpenApiParameter("organization", str, description="Host organization id"),
            OpenApiParameter("when", str, enum=["upcoming", "past"]),
            OpenApiParameter("scope", str, enum=Tournament.Scope.values),
        ]
    )
    def list(self, request):
        """Published tournaments, drafts never. `when=upcoming` (soonest first) covers those still to
        finish; `when=past` (latest first) the completed, cancelled and ended ones."""
        found = tournaments().exclude(status=T.DRAFT)
        scope = request.query_params.get("scope")
        if scope:
            if scope not in Tournament.Scope.values:
                raise ValidationError({"scope": "Choose a tournament scope."})
            found = found.filter(scope=scope)
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
                | Q(organization__region__icontains=term)
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

    @extend_schema(responses={200: TournamentSerializer(many=True)})
    def awaiting_approval(self, request):
        """Drafts whose host asked for approval and that the caller may approve: any of them for a
        platform super admin, otherwise those in the caller's jurisdiction and tier."""
        pending = tournaments().filter(status=T.DRAFT, approval_status=Tournament.Approval.PENDING)
        if not is_platform_super_admin(request.user):
            pending = pending.filter(organization__in=managed_organizations(request.user))
        found = [
            t for t in pending.order_by("starts_on", "name", "id") if lifecycle.can_approve(t, request.user)
        ]
        page = self.paginate_queryset(found)
        return self.get_paginated_response(TournamentSerializer(page, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("when", str, enum=["upcoming", "past"])],
        responses={200: TournamentSerializer(many=True)},
    )
    def overseen(self, request):
        """Published tournaments hosted in the caller's jurisdiction, for regional and country officials
        (and every one for a platform super admin), and in the region of each regional body the caller
        belongs to: what they oversee, whoever organized it. Empty for anybody else. `when=upcoming` (the
        default) covers those still to finish; `when=past` the rest."""
        found = tournaments().exclude(status=T.DRAFT)
        if not is_platform_super_admin(request.user):
            region = Q(pk__in=managed_organizations(request.user).values("pk"))
            bodies = Membership.objects.active().filter(user=request.user, organization__kind__in=BODY_KINDS)
            for body in bodies.select_related("organization"):
                region |= jurisdiction(body.organization)
            found = found.filter(organization__in=Organization.objects.filter(region))
        today = timezone.localdate()
        over = Q(status__in=[T.COMPLETED, T.CANCELLED]) | Q(ends_on__lt=today, status=T.PUBLISHED)
        if request.query_params.get("when") == "past":
            found = found.filter(over).order_by("-starts_on", "name", "id")
        else:
            found = found.exclude(over)
        page = self.paginate_queryset(found)
        return self.get_paginated_response(TournamentSerializer(page, many=True).data)

    def retrieve(self, request, pk):
        tournament = get_object_or_404(tournaments(), pk=pk)
        if tournament.status == T.DRAFT and not sees_draft(request.user, tournament):
            raise Http404
        return Response(TournamentSerializer(tournament).data)

    @extend_schema(operation_id="tournaments_by_slug_retrieve", responses={200: TournamentSerializer})
    def by_slug(self, request, slug):
        """The tournament a public link names, as `retrieve` shows it: a draft only to its staff."""
        if len(slug) > SLUG_MAX_LENGTH:
            raise Http404
        tournament = get_object_or_404(tournaments(), slug=slug)
        if tournament.status == T.DRAFT and not sees_draft(request.user, tournament):
            raise Http404
        return Response(TournamentSerializer(tournament).data)

    def partial_update(self, request, pk):
        with transaction.atomic():
            tournament = approver_tournament(request.user, pk)
            if not manages(request.user, tournament.organization) and set(request.data) - {"scope"}:
                # An official changes only the tier (see lifecycle.ensure_may_change_scope).
                raise ApiException("permission_denied", "Only the host club can change that.", 403)
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
            scope = serializer.validated_data.get("scope", tournament.scope)
            if tournament.status != T.DRAFT and scope != tournament.scope:
                raise ApiException(
                    "structure_frozen", "The tournament scope can't change once it is published.", 409
                )
            if scope != tournament.scope:
                lifecycle.ensure_may_change_scope(tournament, request.user)
            changed = any(
                getattr(tournament, name) != value for name, value in serializer.validated_data.items()
            )
            serializer.save()
            if changed:
                lifecycle.reset_pending_approval(tournament)
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

    def _transition(self, request, pk, change, *, approvers=False, **extra):
        with transaction.atomic():
            find = approver_tournament if approvers else staff_tournament
            tournament = find(request.user, pk)
            change(tournament, request.user, **extra)
        return reply(tournament)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def publish(self, request, pk):
        return self._transition(request, pk, lifecycle.publish, approvers=True)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def request_approval(self, request, pk):
        return self._transition(request, pk, lifecycle.request_approval)

    @extend_schema(request=ReasonSerializer, responses={200: TournamentSerializer})
    def reject_approval(self, request, pk):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._transition(
            request, pk, lifecycle.reject_approval, approvers=True, reason=serializer.validated_data["reason"]
        )

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
        if organization.is_coaching:
            serializer.validated_data.setdefault("presented_as", Tournament.PresentedAs.COACH)
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
            serializer.validated_data.setdefault("entry_fee_minor", tournament.registration_fee_minor)
            serializer.validated_data.setdefault("entry_fee_currency", tournament.registration_fee_currency)
            serializer.save(tournament=tournament, position=0 if last is None else last + 1)
            lifecycle.reset_pending_approval(tournament)
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
            new = serializer.validated_data
            if "kind" in changed and event.entries.filter(status__in=Entry.LIVE).exists():
                raise ApiException(
                    "has_entries", "This event already has entries, so who enters it can't change.", 409
                )
            if new.get("capacity") is not None:
                accepted = event.entries.filter(status=Entry.Status.ACCEPTED).count()
                if new["capacity"] < accepted:
                    raise ValidationError({"capacity": f"{accepted} entries are already accepted."})
            if event.status != E.SCHEDULED and serializer.structure_changes:
                raise ApiException(
                    "structure_frozen",
                    "This event has started, so its format, best of, seeding, groups, qualifiers and "
                    "the make-up of a tie can't change.",
                    409,
                )
            # A lineup names players for the rubbers as they stood when it was handed in.
            if serializer.structure_changes & ties.LINEUP_FIELDS and ties.has_lineups(event):
                raise ApiException(
                    "lineups_in",
                    "A team has handed in a lineup for this event, so the make-up of a tie and the match "
                    "length can't change. Clear the lineups first.",
                    409,
                )
            if changed:
                serializer.save(revision=event.revision + 1)
                lifecycle.reset_pending_approval(tournament)
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
            lifecycle.reset_pending_approval(tournament)
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
    def reopen(self, request, tournament_pk, pk):
        """Platform super admins only: put a completed event back in progress, with the reason, when it was
        completed before all its results were in."""
        if not is_platform_super_admin(request.user):
            raise Http404  # a platform route: "not found" for everyone else
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = get_object_or_404(
                Tournament.objects.select_for_update(of=("self",)), pk=tournament_pk
            )
            lifecycle.reopen_event(
                tournament, self._event(tournament, pk), request.user, serializer.validated_data["reason"]
            )
        return reply(tournament)

    @extend_schema(request=ReasonSerializer, responses={200: TournamentSerializer})
    def cancel(self, request, tournament_pk, pk):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._transition(
            request, tournament_pk, pk, lifecycle.cancel_event, reason=serializer.validated_data["reason"]
        )


def entry_list():
    # Jumbles pairings are made by the draw and shown in its matches, not as entries.
    return (
        Entry.objects.exclude(status=Entry.Status.PAIRING)
        .select_related("event__tournament")
        .prefetch_related("players__user")
    )


class EntryViewSet(viewsets.GenericViewSet):
    """Entries of one event (REQ-008). Open events admit players automatically within capacity.
    Closed events send self-entries to staff for a decision. Accepted entries are visible to signed-in
    players; staff and the entry's own players can also see its other statuses."""

    serializer_class = EntrySerializer
    permission_classes = [PublicReads]
    public_actions = ("list",)  # published tournaments are public (TASK-035)
    pagination_class = StandardPagination

    @property
    def throttle_scope(self):
        # Entering names other players and emails them, so it is rate-limited per caller.
        return "entries" if self.action == "create" else None

    def _reply(self, entry: Entry, code=status.HTTP_200_OK) -> Response:
        fresh = entry_list().get(pk=entry.pk)
        return Response(EntrySerializer(fresh, context={"request": self.request}).data, status=code)

    def _open(self, tournament_pk, event_pk, *, lock: bool) -> tuple[Tournament, Event, bool]:
        """The tournament (locked for a change), the event and whether the caller is its staff. A draft
        doesn't exist for anybody else."""
        found = Tournament.objects.select_related("organization")
        if lock:
            found = found.select_for_update(of=("self",))
        tournament = get_object_or_404(found, pk=tournament_pk)
        staff = manages(self.request.user, tournament.organization)
        if tournament.status == T.DRAFT and not staff:
            raise Http404
        return tournament, get_object_or_404(Event, pk=event_pk, tournament=tournament), staff

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=Entry.Status.values),
            OpenApiParameter("search", str, description="Part of a team's or a player's name."),
        ],
        responses={200: EntrySerializer(many=True)},
    )
    def list(self, request, tournament_pk, event_pk):
        """Accepted entries, plus the caller's own in any status. Competition staff get them all.
        `search` narrows them to entries whose team or one of whose players has the text in its name."""
        _, event, staff = self._open(tournament_pk, event_pk, lock=False)
        found = entry_list().filter(event=event)
        if not staff:
            accepted = Q(status=Entry.Status.ACCEPTED)
            if request.user.is_authenticated:
                accepted |= Q(
                    pk__in=Entry.objects.filter(event=event, players__user=request.user).values("pk")
                )
            found = found.filter(accepted)
        wanted = request.query_params.get("status")
        if wanted:
            if wanted not in Entry.Status.values:
                raise ValidationError({"status": "Not an entry status."})
            found = found.filter(status=wanted)
        term = search_term(request)
        if len(term) > MAX_SEARCH:
            raise ValidationError({"search": f"At most {MAX_SEARCH} characters."})
        if term:
            named = Entry.objects.filter(event=event, players__user__display_name__icontains=term)
            found = found.filter(Q(team_name__icontains=term) | Q(pk__in=named.values("pk")))
        page = self.paginate_queryset(found)
        return self.get_paginated_response(
            EntrySerializer(page, many=True, context={"request": request}).data
        )

    @extend_schema(request=EntryRequestSerializer, responses={201: EntrySerializer})
    def create(self, request, tournament_pk, event_pk):
        """Enter the event during its registration window. Open admission places or waitlists
        the entry. Closed admission sends it to staff for approval. Staff may enter players directly."""
        serializer = EntryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament, event, staff = self._open(tournament_pk, event_pk, lock=True)
            entries.ensure_taking_entries(tournament, event)
            if not staff:
                entries.ensure_registration_open(event)
            ids = asked.get("player_ids") or [request.user.id]
            # Verified players; and, for the host's staff, the host's own unclaimed guests (REQ-003).
            enterable = VERIFIED
            if staff:
                enterable |= Q(
                    guest__organization_id=tournament.organization_id, guest__claimed_by__isnull=True
                )
            known = {user.id: user for user in User.objects.filter(enterable, pk__in=ids, is_active=True)}
            if len(known) != len(ids):
                raise ValidationError({"player_ids": "We don't know one of these players."})
            if not staff and request.user.id not in known:
                raise ValidationError(
                    {"player_ids": "You can only enter yourself, with your partner or team."}
                )
            players = [known[pk] for pk in ids]
            captain = known.get(asked.get("captain_id") or request.user.id)
            team_name = asked.get("team_name", "")
            problem = entries.roster_problem(event, players, team_name, captain)
            if event.kind == Event.Kind.JUMBLES and not asked.get("pool"):
                problem = {**problem, "pool": "Choose the men's or the women's pool."}
            if problem:
                raise ValidationError(problem)
            entry = entries.create(
                event,
                request.user,
                players,
                team_name=team_name,
                captain=captain,
                by_staff=staff,
                pool=asked.get("pool", ""),
            )
        fresh = entry_list().get(pk=entry.pk)
        news = "entered"
        if entry.status == Entry.Status.WAITLISTED:
            news = "waitlisted"
        elif not staff and entry.status == Entry.Status.ACCEPTED:
            news = "accepted"
        send_entry_news(fresh, news, request.user)
        return self._reply(entry, status.HTTP_201_CREATED)

    def _staff_change(self, request, tournament_pk, event_pk, pk, change, *, before_start=True):
        """Run `change(entry)` for the host's competition staff; it returns the news to send, if any."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            entry = get_object_or_404(entry_list(), pk=pk, event_id=event_pk, event__tournament=tournament)
            if before_start:
                entries.ensure_taking_entries(tournament, entry.event)
            elif tournament.status == T.DRAFT or tournament.is_closed or entry.event.is_closed:
                raise ApiException("entries_closed", "Check-in is closed for this event.", 409)
            news = change(entry)
        if news:
            send_entry_news(entry, news, request.user)
        return self._reply(entry)

    @extend_schema(request=None, responses={200: EntrySerializer})
    def accept(self, request, tournament_pk, event_pk, pk):
        """Give the entry a place, from pending or from the waiting list (`event_full` when there is
        none). Its players are told; a promotion from the waiting list says so."""
        return self._staff_change(
            request, tournament_pk, event_pk, pk, lambda entry: entries.accept(entry, request.user)
        )

    @extend_schema(request=None, responses={200: EntrySerializer})
    def waitlist(self, request, tournament_pk, event_pk, pk):
        def change(entry):
            entries.waitlist(entry, request.user)
            return "waitlisted"

        return self._staff_change(request, tournament_pk, event_pk, pk, change)

    def _reason(self, request) -> str:
        serializer = OptionalReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data.get("reason", "")

    @extend_schema(request=OptionalReasonSerializer, responses={200: EntrySerializer})
    def reject(self, request, tournament_pk, event_pk, pk):
        """Turn down a pending or waitlisted entry. The reason, if given, is shown to its players."""
        reason = self._reason(request)

        def change(entry):
            entries.reject(entry, request.user, reason)
            return "rejected"

        return self._staff_change(request, tournament_pk, event_pk, pk, change)

    @extend_schema(request=OptionalReasonSerializer, responses={200: EntrySerializer})
    def staff_withdraw(self, request, tournament_pk, event_pk, pk):
        """Withdraw an entry on its players' behalf. Its place is free again; nobody is promoted
        automatically."""
        reason = self._reason(request)

        def change(entry):
            entries.withdraw(entry, request.user, reason)
            return "withdrawn"

        return self._staff_change(request, tournament_pk, event_pk, pk, change)

    @extend_schema(request=SubstituteSerializer, responses={200: EntrySerializer})
    def substitute(self, request, tournament_pk, event_pk, pk):
        """A player of the entry leaves and someone else plays in their place (TASK-155). The place
        carries on: its results so far stay with it, and the matches already played stay with whoever
        played them. Singles and doubles answer with the new entry that holds the place now (the old
        one is `replaced`); a team keeps its entry with the new player on its roster. Refused while one
        of the entry's matches is being played."""
        serializer = SubstituteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            entry = get_object_or_404(entry_list(), pk=pk, event_id=event_pk, event__tournament=tournament)
            leaving = get_object_or_404(User, pk=asked["leaving_user_id"])
            # Like the entry desk: verified players, or the host's own unclaimed guests (REQ-003).
            enterable = VERIFIED | Q(
                guest__organization_id=tournament.organization_id, guest__claimed_by__isnull=True
            )
            joining = User.objects.filter(enterable, pk=asked["joining_user_id"], is_active=True).first()
            if joining is None:
                raise ValidationError({"joining_user_id": "We don't know this player."})
            taking = substitutes.substitute(entry, leaving, joining, request.user, asked["reason"])
            matchday.log(
                tournament,
                matchday.Action.PLAYER_SWAPPED,
                f"{entry.event.name}: {joining.display_name} plays in place of {leaving.display_name}",
                actor=request.user,
                reason=asked["reason"],
            )
        send_entry_news(taking, "swapped", request.user)
        return self._reply(taking)

    @extend_schema(request=None, responses={200: EntrySerializer})
    def check_in(self, request, tournament_pk, event_pk, pk):
        """The entry has arrived. Independent of the fee, which this API doesn't record yet."""

        def change(entry):
            if entry.checked_in_at is None:
                entries.check_in(entry, request.user)
                matchday.log(
                    tournament_pk, matchday.Action.CHECKED_IN, matchday.entry_title(entry), actor=request.user
                )

        return self._staff_change(request, tournament_pk, event_pk, pk, change, before_start=False)

    @extend_schema(request=None, responses={200: EntrySerializer})
    def undo_check_in(self, request, tournament_pk, event_pk, pk):
        def change(entry):
            if entry.checked_in_at is not None:
                entries.undo_check_in(entry)
                matchday.log(
                    tournament_pk,
                    matchday.Action.CHECK_IN_UNDONE,
                    matchday.entry_title(entry),
                    actor=request.user,
                )

        return self._staff_change(request, tournament_pk, event_pk, pk, change, before_start=False)

    @extend_schema(request=None, responses={200: EntrySerializer})
    def self_check_in(self, request, tournament_pk, event_pk, pk):
        with transaction.atomic():
            tournament, event, _ = self._open(tournament_pk, event_pk, lock=True)
            entry = get_object_or_404(entry_list(), pk=pk, event=event, players__user=request.user)
            if tournament.status == T.DRAFT or tournament.is_closed or event.is_closed:
                raise ApiException("entries_closed", "Check-in is closed for this event.", 409)
            entries.self_check_in(entry, request.user, tournament)
        return self._reply(entry)

    @extend_schema(request=None, responses={200: EntrySerializer})
    def withdraw(self, request, tournament_pk, event_pk, pk):
        """By one of the entry's own players, before the event starts. For anybody else the entry
        doesn't exist here."""
        with transaction.atomic():
            tournament, event, _ = self._open(tournament_pk, event_pk, lock=True)
            entry = get_object_or_404(entry_list(), pk=pk, event=event, players__user=request.user)
            entries.ensure_taking_entries(tournament, event)
            entries.withdraw(entry, request.user)
        send_entry_news(entry, "withdrawn", request.user)
        return self._reply(entry)


class MyEntriesViewSet(viewsets.GenericViewSet):
    """Every entry the caller plays in, newest first, with its event and tournament."""

    serializer_class = MyEntrySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def list(self, request):
        mine = Entry.objects.filter(players__user=request.user).values("pk")
        found = (
            entry_list()
            .filter(pk__in=mine)
            .exclude(event__tournament__status=T.DRAFT)
            .order_by("-created_at", "id")
        )
        page = self.paginate_queryset(found)
        return self.get_paginated_response(
            MyEntrySerializer(page, many=True, context={"request": request}).data
        )


class DrawViewSet(viewsets.GenericViewSet):
    """The draw of one event (REQ-009). The published draw is open to every signed-in player; the
    preview, and making and publishing draws, are for the host's competition staff."""

    serializer_class = EventDrawSerializer
    permission_classes = [PublicReads]
    public_actions = ("retrieve", "standings", "match")  # published tournaments are public (TASK-035)

    def _shown(self, event: Event, staff: bool) -> Response:
        status = DrawVersion.Status
        by_status = {draw.status: draw for draw in event.draws.exclude(status=status.SUPERSEDED)}
        published = by_status.get(status.PUBLISHED)
        preview = by_status.get(status.PREVIEW) if staff else None
        return Response(
            EventDrawSerializer(
                {
                    "published": drawing.describe(published, staff) if published else None,
                    "preview": drawing.describe(preview, staff) if preview else None,
                    "recommended_seeds": drawing.rating_seeds(event)
                    if staff and event.status == E.SCHEDULED
                    else [],
                },
                context={"request": self.request},
            ).data
        )

    def _published(self, request, tournament_pk, event_pk) -> DrawVersion | None:
        """The event's published draw, if it has one. A draft tournament doesn't exist for anybody but
        its staff."""
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        if tournament.status == T.DRAFT and not manages(request.user, tournament.organization):
            raise Http404
        event = get_object_or_404(Event, pk=event_pk, tournament=tournament)
        return (
            event.draws.filter(status=DrawVersion.Status.PUBLISHED)
            .select_related("event__tournament__organization")
            .first()
        )

    @extend_schema(responses={200: EventDrawSerializer})
    def retrieve(self, request, tournament_pk, event_pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        staff = manages(request.user, tournament.organization)
        if tournament.status == T.DRAFT and not staff:
            raise Http404
        return self._shown(get_object_or_404(Event, pk=event_pk, tournament=tournament), staff)

    @extend_schema(responses={200: StandingsSerializer})
    def standings(self, request, tournament_pk, event_pk):
        """Standings of the published draw: each group ranked under ITTF 3.7.5 with the comparisons
        that separated level members, and the knockout placements decided so far. Empty until a draw is
        published."""
        draw = self._published(request, tournament_pk, event_pk)
        shown = drawing.standings_of(draw) if draw else {"rules_version": "", "groups": [], "placements": []}
        return Response(StandingsSerializer(shown, context={"request": request}).data)

    @extend_schema(responses={200: MatchDetailSerializer})
    def match(self, request, tournament_pk, event_pk, pk):
        """One match of the published draw: sides, games, table and time. A match of a preview or of a
        superseded draw doesn't exist here."""
        draw = self._published(request, tournament_pk, event_pk)
        return match_reply(request, draw, pk)

    def _tie(self, request, tournament_pk, event_pk, pk) -> tuple[Match, bool]:
        """The tie (a match of the published draw of a team event), with the tournament locked for a
        change, and whether the caller is competition staff. Call inside a transaction."""
        tournament = get_object_or_404(
            Tournament.objects.select_for_update(of=("self",)).select_related("organization"),
            pk=tournament_pk,
        )
        staff = manages(request.user, tournament.organization)
        if tournament.status == T.DRAFT and not staff:
            raise Http404
        match = get_object_or_404(
            Match.objects.select_related("draw__event__tournament__organization"),
            pk=pk,
            draw__event_id=event_pk,
            draw__event__tournament=tournament,
            draw__status=DrawVersion.Status.PUBLISHED,
        )
        return match, staff

    @extend_schema(request=LineupRequestSerializer, responses={200: MatchDetailSerializer})
    def lineup(self, request, tournament_pk, event_pk, pk):
        """Hand in or replace a team's lineup for a tie: by the team's captain or by competition staff,
        until both lineups are in. The other team sees only that it has been handed in. When both are
        in the tie begins and its rubbers are made."""
        serializer = LineupRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            match, staff = self._tie(request, tournament_pk, event_pk, pk)
            entry = Entry.objects.filter(
                pk=asked["entry_id"], pk__in=[match.entry_a_id, match.entry_b_id]
            ).first()
            if not staff and (entry is None or entry.captain_id != request.user.id):
                raise ApiException(
                    "permission_denied", "Only the team's captain or the organizers hand in its lineup.", 403
                )
            if entry is None:
                raise ApiException("not_in_match", "That team doesn't play in this tie.", 409)
            picks = [[str(pk) for pk in players] for players in asked["picks"]]
            ties.submit_lineup(match, entry, request.user, picks)
        return match_reply(request, match.draw, match.id)

    @extend_schema(request=None, responses={200: MatchDetailSerializer})
    def lineup_reset(self, request, tournament_pk, event_pk, pk):
        """Competition staff send both teams back to choose again, while no rubber has been decided."""
        with transaction.atomic():
            match, staff = self._tie(request, tournament_pk, event_pk, pk)
            if not staff:
                raise ApiException(
                    "permission_denied", "Your role in this organization doesn't allow that.", 403
                )
            ties.reset_lineups(match)
        return match_reply(request, match.draw, match.id)

    @extend_schema(request=DrawRequestSerializer, responses={200: EventDrawSerializer})
    def preview(self, request, tournament_pk, event_pk):
        """Draw the accepted entries (again). Seeds are given best first; the rest is drawn by lot from
        `rng_seed`, so the same request always gives the same draw. Replaces the last preview and
        changes nothing anybody else can see."""
        serializer = DrawRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            event = get_object_or_404(Event, pk=event_pk, tournament=tournament)
            drawing.ensure_drawable(tournament, event)
            seeds = (
                [str(pk) for pk in asked["seeded_entry_ids"]]
                if "seeded_entry_ids" in asked
                else drawing.rating_seeds(event)
            )
            drawing.make_preview(
                event,
                request.user,
                seeds,
                asked.get("rng_seed"),
                keep_apart=asked.get("keep_apart", drawing.KEEP_APART),
                limit=asked.get("same_group_limit", drawing.draws.SAME_GROUP_LIMIT),
            )
        return self._shown(event, staff=True)

    @extend_schema(request=DrawMoveSerializer, responses={200: EventDrawSerializer})
    def move(self, request, tournament_pk, event_pk):
        """Move an entry of the preview by hand, into another group or into another entry's place. The
        matches it touches are made again. Groups over the limit on one club, team or region are listed
        in `over_limit`; the draw can't be published until none is."""
        with transaction.atomic():
            # Who may move comes first, so nobody else learns anything from the body's validation.
            tournament = staff_tournament(request.user, tournament_pk)
            event = get_object_or_404(Event, pk=event_pk, tournament=tournament)
            serializer = DrawMoveSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            asked = serializer.validated_data
            drawing.ensure_drawable(tournament, event)
            entry_id = str(asked["entry_id"])
            preview = event.draws.filter(status=DrawVersion.Status.PREVIEW).first()
            placed = preview is not None and preview.places.filter(entry_id=entry_id).exists()
            if asked.get("remove"):
                drawing.remove_entry(event, request.user, entry_id)
            elif "group" in asked and preview is not None and not placed:
                drawing.add_entry(event, request.user, entry_id, asked["group"])
            else:
                drawing.move(
                    event,
                    request.user,
                    entry_id,
                    group=asked.get("group"),
                    swap_with=str(asked["swap_with"]) if "swap_with" in asked else None,
                )
        return self._shown(event, staff=True)

    @extend_schema(request=None, responses={200: EventDrawSerializer})
    def reopen(self, request, tournament_pk, event_pk):
        """Take the published draw up again as the preview, exactly as it is, to add late entries to a
        group or take withdrawn ones out without drawing again. Publishing it makes a new version.
        Replaces a preview being worked on."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            event = get_object_or_404(Event, pk=event_pk, tournament=tournament)
            drawing.ensure_drawable(tournament, event)
            drawing.reopen(event, request.user)
        return self._shown(event, staff=True)

    @extend_schema(request=None, responses={200: EventDrawSerializer})
    def discard(self, request, tournament_pk, event_pk):
        """Delete the preview, before it is published, to start the draw again. The published draw is
        untouched, and with no preview nothing changes."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            event = get_object_or_404(Event, pk=event_pk, tournament=tournament)
            drawing.ensure_drawable(tournament, event)
            drawing.discard_preview(event)
        return self._shown(event, staff=True)

    @extend_schema(request=None, responses={200: EventDrawSerializer})
    def publish(self, request, tournament_pk, event_pk):
        """Publish the preview as the event's draw, superseding the one before. Refused when the
        accepted entries have changed since it was drawn (`draw_stale`)."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            event = get_object_or_404(Event, pk=event_pk, tournament=tournament)
            drawing.ensure_drawable(tournament, event)
            drawing.publish(event, request.user)
        return self._shown(event, staff=True)


class TournamentPlayerView(APIView):
    """One player in one tournament (TASK-148): their profile as the reader may see it, and their
    entries, draw places, matches and placings there. A draft tournament, a player with no part in it
    and a player whose only entries the reader may not see are all "not found"."""

    permission_classes = [PublicReads]
    public_actions = ("get",)  # published tournaments are public (TASK-035)

    @extend_schema(responses={200: TournamentPlayerSerializer})
    def get(self, request, tournament_pk, pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        staff = manages(request.user, tournament.organization)
        if tournament.status == T.DRAFT and not staff:
            raise Http404
        player = get_object_or_404(User, pk=pk)
        shown = player_record.record(tournament, player, request.user, staff)
        if shown is None:
            raise Http404
        return Response(TournamentPlayerSerializer(shown, context={"request": request}).data)
