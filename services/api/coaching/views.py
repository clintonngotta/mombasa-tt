"""Coaching API (REQ-047).

Coaches are found at /coaches/. Everything else is under /me/ and scoped to the caller: their coach
profile and availability, coachings on either side, bookings on either side, the trainees they coach and
the coach's notes on their own matches. A coach reaches a trainee's matches and plans only through an
active coaching, so anyone else, or a coach whose coaching has ended, gets 404.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Avg, BooleanField, Count, ExpressionWrapper, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from competitions.models import Tournament
from core.exceptions import ApiException
from core.pagination import StandardPagination
from matchlog.models import PersonalMatch
from organizations.models import Membership
from ratings.models import Rating
from training import service as training
from training.models import PlanItem, TrainingPlan
from training.serializers import DrillRecommendationSerializer, TrainingPlanSerializer
from training.views import PlanItemsBase, recommendations_for, with_items

from . import service
from .models import Availability, Booking, Coaching, CoachProfile, CoachRating, MatchComment
from .serializers import (
    AssignPlanSerializer,
    AvailabilityListSerializer,
    AvailabilitySerializer,
    BookingReasonSerializer,
    BookingRequestSerializer,
    BookingSerializer,
    CalendarEntrySerializer,
    CoachingRequestSerializer,
    CoachingSerializer,
    CoachOrganizerRequestSerializer,
    CoachOrganizerSerializer,
    CoachProfileSerializer,
    CoachRatingSerializer,
    CommentInputSerializer,
    CommentSerializer,
    SlotSerializer,
    TraineeSerializer,
    official_row,
    personal_row,
)

User = get_user_model()
RECENT_MATCHES = 15


def profiles(viewer):
    """Coach profiles with their star rating, the viewer's own rating and whether the viewer may rate."""
    mine = CoachRating.objects.filter(coach=OuterRef("user"), player=viewer).values("stars")[:1]
    return (
        CoachProfile.objects.select_related("user")
        .prefetch_related("organizations", "user__coach_availability")
        .annotate(
            rating_average=Avg("user__coach_ratings__stars"),
            rating_count=Count("user__coach_ratings"),
            my_rating=Subquery(mine),
            can_rate=ExpressionWrapper(service.trained_with(viewer), output_field=BooleanField()),
        )
    )


# Coach profiles ---------------------------------------------------------------------------------------


class CoachListView(ListAPIView):
    """GET /coaches/: coaches taking players, filtered by name, town, region or a skill they teach."""

    serializer_class = CoachProfileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Name, headline or town"),
            OpenApiParameter("region", str),
            OpenApiParameter("skill", str),
            OpenApiParameter("level", str),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        found = profiles(self.request.user).filter(accepting=True, user__is_active=True)
        params = self.request.query_params
        if params.get("search"):
            term = params["search"].strip()[:80]
            found = found.filter(
                Q(user__display_name__icontains=term) | Q(headline__icontains=term) | Q(town__icontains=term)
            )
        if params.get("region"):
            found = found.filter(region__iexact=params["region"].strip())
        if params.get("skill"):
            found = found.filter(specialties__contains=[params["skill"]])
        if params.get("level"):
            found = found.filter(levels__contains=[params["level"]])
        return found.order_by("user__display_name")


class CoachDetailView(APIView):
    """GET /coaches/{user id}/: a coach's profile. Their trainees still see it after they stop taking
    new players."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CoachProfileSerializer})
    def get(self, request, pk):
        profile = get_object_or_404(profiles(request.user), user_id=pk)
        if not profile.accepting and profile.user_id != request.user.pk:
            if (
                not Coaching.objects.filter(coach_id=pk, trainee=request.user)
                .exclude(status=Coaching.Status.DECLINED)
                .exists()
            ):
                raise ApiException("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        return Response(CoachProfileSerializer(profile, context={"request": request}).data)


class CoachSlotsView(APIView):
    """GET /coaches/{user id}/slots/: free start times for a session in the next days."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "from", date, description="First day, in the coach's timezone; today by default"
            ),
            OpenApiParameter("days", int, description="1 to 28, default 14"),
            OpenApiParameter("minutes", int, description="Session length, 30 to 180, default 60"),
        ],
        responses={200: SlotSerializer(many=True)},
    )
    def get(self, request, pk):
        profile = get_object_or_404(CoachProfile.objects.select_related("user"), user_id=pk)
        params = request.query_params
        try:
            days = min(max(int(params.get("days", 14)), 1), 28)
            minutes = min(max(int(params.get("minutes", 60)), 30), 180)
            first = date.fromisoformat(params["from"]) if params.get("from") else None
        except ValueError as error:
            raise ValidationError({"from": "Use YYYY-MM-DD and whole numbers."}) from error
        first = first or timezone.now().astimezone(ZoneInfo(profile.timezone)).date()
        slots = service.free_slots(profile, first, days, minutes)
        return Response(SlotSerializer(slots, many=True).data)


class CoachRatingView(APIView):
    """PUT /coaches/{user id}/rating/: the caller's star rating of a coach they trained with, set or
    changed; DELETE removes it. The answer is the coach's profile with the new average."""

    permission_classes = [IsAuthenticated]

    def coach(self, request, pk) -> CoachProfile:
        profile = get_object_or_404(profiles(request.user).filter(user__is_active=True), user_id=pk)
        if not profile.can_rate:
            # A coach who isn't listed is hidden from people they never trained.
            if not profile.accepting:
                raise ApiException("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
            raise ApiException(
                "cannot_rate",
                "You can rate a coach once you have trained with them.",
                status.HTTP_403_FORBIDDEN,
            )
        return profile

    def answer(self, request, pk):
        profile = get_object_or_404(profiles(request.user), user_id=pk)
        return Response(CoachProfileSerializer(profile, context={"request": request}).data)

    @extend_schema(request=CoachRatingSerializer, responses={200: CoachProfileSerializer})
    def put(self, request, pk):
        serializer = CoachRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.coach(request, pk)
        CoachRating.objects.update_or_create(
            coach_id=pk, player=request.user, defaults={"stars": serializer.validated_data["stars"]}
        )
        return self.answer(request, pk)

    @extend_schema(request=None, responses={200: CoachProfileSerializer})
    def delete(self, request, pk):
        self.coach(request, pk)
        CoachRating.objects.filter(coach_id=pk, player=request.user).delete()
        return self.answer(request, pk)


class MyCoachProfileView(APIView):
    """GET/PUT /me/coach-profile/: the caller's coach profile; PUT switches it on or changes it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CoachProfileSerializer})
    def get(self, request):
        profile = get_object_or_404(profiles(request.user), user=request.user)
        return Response(CoachProfileSerializer(profile, context={"request": request}).data)

    @extend_schema(request=CoachProfileSerializer, responses={200: CoachProfileSerializer})
    def put(self, request):
        profile = CoachProfile.objects.filter(user=request.user).first()
        serializer = CoachProfileSerializer(
            profile, data=request.data, partial=profile is not None, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        profile = serializer.save(user=request.user)
        return Response(
            CoachProfileSerializer(
                get_object_or_404(profiles(request.user), pk=profile.pk), context={"request": request}
            ).data
        )


class MyOrganizerView(APIView):
    """POST /me/coach-profile/organizer/: the coach's organizing desk, made the first time they organize a
    tournament. The coach is its only admin, so its tournaments run like any club's. Each of its tournaments
    names the coach or their firm as organizer (Tournament.presented_as); the desk takes the name chosen
    here."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=CoachOrganizerRequestSerializer, responses={200: CoachOrganizerSerializer})
    def post(self, request):
        body = CoachOrganizerRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            profile = get_object_or_404(
                CoachProfile.objects.select_for_update().select_related("user"), user=request.user
            )
            desk = service.open_organizer(profile, body.validated_data["presented_as"])
        return Response(CoachOrganizerSerializer({"organization_id": desk.id, "name": desk.name}).data)


class MyAvailabilityView(APIView):
    """GET/PUT /me/coach-availability/: the coach's weekly windows; PUT replaces them all."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AvailabilitySerializer(many=True)})
    def get(self, request):
        return Response(
            AvailabilitySerializer(Availability.objects.filter(coach=request.user), many=True).data
        )

    @extend_schema(request=AvailabilityListSerializer, responses={200: AvailabilitySerializer(many=True)})
    def put(self, request):
        get_object_or_404(CoachProfile, user=request.user)
        serializer = AvailabilityListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            Availability.objects.filter(coach=request.user).delete()
            Availability.objects.bulk_create(
                Availability(coach=request.user, **window) for window in serializer.validated_data["windows"]
            )
        return self.get(request)


# Coachings --------------------------------------------------------------------------------------------


def mine(user):
    return Coaching.objects.filter(Q(coach=user) | Q(trainee=user)).select_related("coach", "trainee")


class MyCoachingsView(APIView):
    """GET /me/coachings/: coachings on either side, open ones first. POST asks a coach to coach you, or,
    as a coach, invites a player."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CoachingSerializer(many=True)})
    def get(self, request):
        coachings = mine(request.user).exclude(status=Coaching.Status.DECLINED)
        open_first = sorted(
            coachings, key=lambda c: (c.status == Coaching.Status.ENDED, -c.created_at.timestamp())
        )
        return Response(CoachingSerializer(open_first, many=True, context={"request": request}).data)

    @extend_schema(request=CoachingRequestSerializer, responses={201: CoachingSerializer})
    def post(self, request):
        serializer = CoachingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("coach_id"):
            profile = get_object_or_404(CoachProfile, user_id=data["coach_id"], user__is_active=True)
            if not profile.accepting:
                raise ApiException("not_accepting", "This coach isn't taking new players at the moment.")
            coach, trainee = profile.user, request.user
        else:
            get_object_or_404(CoachProfile, user=request.user)
            coach, trainee = request.user, get_object_or_404(User, pk=data["trainee_id"], is_active=True)
        if coach.pk == trainee.pk:
            raise ApiException("own_coaching", "You can't coach yourself.")
        try:
            with transaction.atomic():
                coaching = Coaching.objects.create(
                    coach=coach, trainee=trainee, requested_by=request.user, message=data.get("message", "")
                )
        except IntegrityError as error:
            raise ApiException(
                "coaching_exists", "You already have a request or a coaching with this person.", 409
            ) from error
        return Response(
            CoachingSerializer(coaching, context={"request": request}).data, status=status.HTTP_201_CREATED
        )


class CoachingActionView(APIView):
    """POST /me/coachings/{id}/{accept|decline|end}/."""

    permission_classes = [IsAuthenticated]
    action = ""

    @extend_schema(request=None, responses={200: CoachingSerializer})
    def post(self, request, pk):
        with transaction.atomic():
            coaching = get_object_or_404(mine(request.user).select_for_update(of=("self",)), pk=pk)
            now = timezone.now()
            if self.action in ("accept", "decline"):
                if (
                    coaching.status != Coaching.Status.REQUESTED
                    or coaching.requested_by_id == request.user.pk
                ):
                    raise ApiException("not_awaiting_you", "This request isn't waiting for your answer.", 409)
                coaching.status = (
                    Coaching.Status.ACTIVE if self.action == "accept" else Coaching.Status.DECLINED
                )
                if self.action == "accept":
                    coaching.started_at = now
                else:
                    coaching.ended_at = now
            else:
                if coaching.status not in (Coaching.Status.REQUESTED, Coaching.Status.ACTIVE):
                    raise ApiException("already_ended", "This coaching has already ended.", 409)
                coaching.status = Coaching.Status.ENDED
                coaching.ended_at = now
            coaching.save()
        return Response(CoachingSerializer(coaching, context={"request": request}).data)


# Trainees, seen by their coach -------------------------------------------------------------------------


def comments_for(coach, trainee):
    """The coach's comments on the trainee's matches, keyed by ("personal" | "official", match id)."""
    found: dict[tuple[str, str], list] = {}
    for comment in MatchComment.objects.filter(coach=coach, trainee=trainee).select_related("coach"):
        key = (
            ("personal", comment.personal_match_id)
            if comment.personal_match_id
            else ("official", comment.match_id)
        )
        found.setdefault(key, []).append(CommentSerializer(comment).data)
    return found


def trainee_matches(coach, trainee) -> list[dict]:
    comments = comments_for(coach, trainee)
    personal = PersonalMatch.objects.filter(owner=trainee).prefetch_related("games")[:RECENT_MATCHES]
    official = (
        service.official_matches(trainee)
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
        .order_by("-scheduled_at", "-draw__event__tournament__starts_on")[:RECENT_MATCHES]
    )
    rows = [personal_row(m, comments.get(("personal", m.id), [])) for m in personal]
    rows += [official_row(m, trainee, comments.get(("official", m.id), [])) for m in official]
    return sorted(rows, key=lambda r: r["played_on"] or date.min, reverse=True)


class TraineeView(APIView):
    """GET /me/trainees/{coaching id}/: a trainee's progress, for their coach."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: TraineeSerializer})
    def get(self, request, pk):
        coaching = service.active_coaching(request.user, pk)
        trainee = coaching.trainee
        plans = with_items(
            TrainingPlan.objects.filter(owner=trainee, coach=request.user).select_related("coach")
        )
        matches = trainee_matches(request.user, trainee)
        record = {
            "won": sum(1 for m in matches if m["result"] == "win"),
            "lost": sum(1 for m in matches if m["result"] == "loss"),
        }
        bookings = Booking.objects.filter(
            coach=request.user, trainee=trainee, ends_at__gte=timezone.now() - timedelta(days=30)
        ).select_related("coach", "trainee")
        ratings = [
            {"discipline": r.discipline, "rating": round(r.rating, 1), "played": r.played, "won": r.won}
            for r in Rating.objects.filter(user=trainee)
        ]
        data = {
            "coaching": coaching,
            "plans": plans,
            "matches": matches,
            "ratings": ratings,
            "bookings": bookings,
            "record": record,
        }
        return Response(TraineeSerializer(data, context={"request": request}).data)


class TraineePlansView(APIView):
    """POST /me/trainees/{coaching id}/plans/: give the trainee a plan, copied from one of yours or a
    club plan you can read, or a new empty one. The trainee owns it; its sessions go in their calendar."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=AssignPlanSerializer, responses={201: TrainingPlanSerializer})
    def post(self, request, pk):
        service.active_coaching(request.user, pk)  # anybody else is turned away before validation
        serializer = AssignPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            coaching = service.active_coaching(request.user, pk)
            trainee = coaching.trainee
            training.lock_player(trainee)
            source = None
            if data.get("source_plan_id"):
                clubs = Membership.objects.active().filter(user=request.user).values("organization")
                source = get_object_or_404(
                    with_items(
                        TrainingPlan.objects.filter(Q(owner=request.user) | Q(organization__in=clubs))
                    ),
                    pk=data["source_plan_id"],
                )
            plan = TrainingPlan.objects.create(
                owner=trainee,
                coach=request.user,
                created_by=request.user,
                title=data.get("title") or source.title,
                goal=source.goal if source else "",
                goal_skills=source.goal_skills if source else [],
                period=source.period if source else TrainingPlan.Period.CUSTOM,
                starts_on=source.starts_on if source else None,
                ends_on=source.ends_on if source else None,
            )
            for item in source.items.all() if source else []:
                if item.kind == PlanItem.Kind.SESSION:
                    # A past session isn't copied; a future one must fit the trainee's calendar.
                    if item.starts_at <= timezone.now():
                        continue
                    training.ensure_free(
                        trainee,
                        item.starts_at,
                        item.ends_at,
                        message=f"{trainee.display_name} already has something on during “{item.title}”.",
                    )
                PlanItem.objects.create(
                    plan=plan,
                    kind=item.kind,
                    title=item.title,
                    notes=item.notes,
                    drill=item.drill,
                    order=item.order,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    activities=item.activities,
                )
        return Response(
            TrainingPlanSerializer(
                with_items(TrainingPlan.objects.select_related("coach")).get(pk=plan.pk)
            ).data,
            status=status.HTTP_201_CREATED,
        )


class TraineePlanView(APIView):
    """PATCH/DELETE /me/trainees/{coaching id}/plans/{plan id}/: a plan the coach gave the trainee."""

    permission_classes = [IsAuthenticated]

    def plan(self, request, pk, plan_pk):
        coaching = service.active_coaching(request.user, pk)
        return get_object_or_404(TrainingPlan, pk=plan_pk, owner=coaching.trainee, coach=request.user)

    @extend_schema(responses={200: TrainingPlanSerializer})
    def get(self, request, pk, plan_pk):
        plan = self.plan(request, pk, plan_pk)
        return Response(
            TrainingPlanSerializer(
                with_items(TrainingPlan.objects.select_related("coach")).get(pk=plan.pk)
            ).data
        )

    @extend_schema(request=TrainingPlanSerializer, responses={200: TrainingPlanSerializer})
    def patch(self, request, pk, plan_pk):
        plan = self.plan(request, pk, plan_pk)
        serializer = TrainingPlanSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            TrainingPlanSerializer(
                with_items(TrainingPlan.objects.select_related("coach")).get(pk=plan.pk)
            ).data
        )

    @extend_schema(responses={204: None})
    def delete(self, request, pk, plan_pk):
        self.plan(request, pk, plan_pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TraineePlanRecommendationsView(TraineePlanView):
    """GET /me/trainees/{coaching id}/plans/{plan id}/recommendations/: drills from the coach's library
    for the plan's goal skills."""

    http_method_names = ["get"]

    @extend_schema(responses={200: DrillRecommendationSerializer(many=True)})
    def get(self, request, pk, plan_pk):
        return recommendations_for(self.plan(request, pk, plan_pk), training.usable_drills(request.user))


class TraineePlanItemViewSet(PlanItemsBase):
    """Items of a plan the coach gave the trainee. Sessions are checked against the trainee's calendar."""

    def coaching(self) -> Coaching:
        return service.active_coaching(self.request.user, self.kwargs["coaching_pk"])

    def plan(self):
        coaching = self.coaching()
        return get_object_or_404(
            TrainingPlan, pk=self.kwargs["plan_pk"], owner=coaching.trainee, coach=self.request.user
        )

    def drills(self):
        return training.usable_drills(self.request.user)

    def calendar_owner(self):
        return self.coaching().trainee


class TraineeCommentsView(APIView):
    """POST /me/trainees/{coaching id}/comments/: comment on one of the trainee's matches. Only the
    trainee and you read it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=CommentInputSerializer, responses={201: CommentSerializer})
    def post(self, request, pk):
        coaching = service.active_coaching(request.user, pk)
        serializer = CommentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        target = {}
        if data.get("personal_match"):
            target["personal_match"] = get_object_or_404(
                PersonalMatch, pk=data["personal_match"], owner=coaching.trainee
            )
        else:
            target["match"] = get_object_or_404(service.official_matches(coaching.trainee), pk=data["match"])
        comment = MatchComment.objects.create(
            coach=request.user, trainee=coaching.trainee, body=data["body"], **target
        )
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class CoachCommentView(APIView):
    """PATCH/DELETE /me/coach-comments/{id}/: the coach changes or removes a comment they wrote, while
    they still coach the trainee."""

    permission_classes = [IsAuthenticated]

    def comment(self, request, pk) -> MatchComment:
        comment = get_object_or_404(MatchComment.objects.select_related("coach"), pk=pk, coach=request.user)
        if not service.coaches(request.user, comment.trainee_id):
            raise ApiException("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        return comment

    @extend_schema(request=CommentSerializer, responses={200: CommentSerializer})
    def patch(self, request, pk):
        comment = self.comment(request, pk)
        serializer = CommentSerializer(comment, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(CommentSerializer(serializer.save()).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        self.comment(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyCoachNotesView(APIView):
    """GET /me/coach-notes/: what coaches wrote about the caller's matches, oldest first. Filter by one
    match with `personal_match` or `match`."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("personal_match", str), OpenApiParameter("match", str)],
        responses={200: CommentSerializer(many=True)},
    )
    def get(self, request):
        notes = MatchComment.objects.filter(trainee=request.user).select_related("coach")
        try:
            if request.query_params.get("personal_match"):
                notes = notes.filter(personal_match=request.query_params["personal_match"])
            if request.query_params.get("match"):
                notes = notes.filter(match=request.query_params["match"])
        except ValueError:
            notes = notes.none()
        return Response(CommentSerializer(notes[:200], many=True).data)


# Bookings ----------------------------------------------------------------------------------------------


def my_bookings(user):
    return Booking.objects.filter(Q(coach=user) | Q(trainee=user)).select_related("coach", "trainee")


class MyBookingsView(APIView):
    """GET /me/bookings/: sessions booked with or by the caller, upcoming by default. POST asks a coach
    for a session at a free time."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("past", bool, description="Sessions that have ended, newest first")],
        responses={200: BookingSerializer(many=True)},
    )
    def get(self, request):
        now = timezone.now()
        if request.query_params.get("past") in ("1", "true"):
            bookings = my_bookings(request.user).filter(ends_at__lt=now).order_by("-starts_at")[:50]
        else:
            bookings = my_bookings(request.user).filter(ends_at__gte=now).order_by("starts_at")[:100]
        return Response(BookingSerializer(bookings, many=True, context={"request": request}).data)

    @extend_schema(request=BookingRequestSerializer, responses={201: BookingSerializer})
    def post(self, request):
        serializer = BookingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        profile = get_object_or_404(CoachProfile.objects.select_related("user"), user_id=data["coach_id"])
        starts, ends = data["starts_at"], data["ends_at"]
        service.check_booking(profile, request.user, starts, ends)
        with transaction.atomic():
            service.lock_people(profile.user, request.user)
            training.ensure_free(request.user, starts, ends, with_coach=profile.user)
            training.ensure_free(profile.user, starts, ends, message="The coach isn't free at that time.")
            booking = Booking.objects.create(
                coach=profile.user,
                trainee=request.user,
                starts_at=starts,
                ends_at=ends,
                venue=data.get("venue", ""),
                note=data.get("note", ""),
                changed_by=request.user,
            )
        return Response(
            BookingSerializer(booking, context={"request": request}).data, status=status.HTTP_201_CREATED
        )


class BookingActionView(APIView):
    """POST /me/bookings/{id}/{confirm|decline|cancel}/. The coach confirms or declines a request; either
    person cancels a booking that hasn't started."""

    permission_classes = [IsAuthenticated]
    action = ""

    @extend_schema(request=BookingReasonSerializer, responses={200: BookingSerializer})
    def post(self, request, pk):
        serializer = BookingReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            booking = get_object_or_404(my_bookings(request.user).select_for_update(of=("self",)), pk=pk)
            is_coach = booking.coach_id == request.user.pk
            if self.action in ("confirm", "decline"):
                if not is_coach:
                    raise ApiException("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
                if booking.status != Booking.Status.REQUESTED:
                    raise ApiException("not_requested", "This session isn't waiting for an answer.", 409)
                booking.status = (
                    Booking.Status.CONFIRMED if self.action == "confirm" else Booking.Status.DECLINED
                )
            else:
                if booking.status not in Booking.HOLDING:
                    raise ApiException("not_booked", "This session isn't booked.", 409)
                if booking.starts_at <= timezone.now():
                    raise ApiException("already_started", "This session has already started.", 409)
                booking.status = Booking.Status.CANCELLED
            booking.reason = serializer.validated_data.get("reason", "")
            booking.changed_by = request.user
            booking.save()
        return Response(BookingSerializer(booking, context={"request": request}).data)


# The coach's calendar ----------------------------------------------------------------------------------


def _entry(
    kind,
    id,
    title,
    *,
    detail="",
    starts_at=None,
    ends_at=None,
    starts_on=None,
    ends_on=None,
    status="",
    link="",
):
    return {
        "kind": kind,
        "id": id,
        "title": title,
        "detail": detail,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "status": status,
        "link": link,
    }


class CoachCalendarView(APIView):
    """GET /me/coach-calendar/?from=&to=: the coach's bookings, their own sessions, sessions of plans they
    gave trainees, and the training timetable and tournaments of the clubs where they coach. At most 62
    days; this week by default."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("from", date), OpenApiParameter("to", date)],
        responses={200: CalendarEntrySerializer(many=True)},
    )
    def get(self, request):
        profile = CoachProfile.objects.filter(user=request.user).first()
        tz = ZoneInfo(profile.timezone if profile else "Africa/Nairobi")
        today = timezone.now().astimezone(tz).date()
        try:
            first = (
                date.fromisoformat(request.query_params["from"])
                if request.query_params.get("from")
                else today - timedelta(days=today.weekday())
            )
            last = (
                date.fromisoformat(request.query_params["to"])
                if request.query_params.get("to")
                else first + timedelta(days=6)
            )
        except ValueError as error:
            raise ValidationError({"from": "Use YYYY-MM-DD."}) from error
        if last < first or (last - first).days > 62:
            raise ValidationError({"to": "Choose at most 62 days, ending after they start."})
        starts = datetime.combine(first, datetime.min.time(), tz)
        ends = datetime.combine(last + timedelta(days=1), datetime.min.time(), tz)
        overlapping = {"starts_at__lt": ends, "ends_at__gt": starts}
        entries = []
        for booking in my_bookings(request.user).filter(status__in=Booking.HOLDING, **overlapping):
            coaching = booking.coach_id == request.user.pk
            other = booking.trainee if coaching else booking.coach
            entries.append(
                _entry(
                    "booking",
                    booking.id,
                    f"Session with {other.display_name}",
                    detail=booking.venue,
                    starts_at=booking.starts_at,
                    ends_at=booking.ends_at,
                    status=booking.status,
                )
            )
        sessions = PlanItem.objects.filter(kind=PlanItem.Kind.SESSION, **overlapping).select_related(
            "plan__owner", "plan__organization"
        )
        for item in sessions.filter(plan__owner=request.user):
            entries.append(
                _entry(
                    "session",
                    item.id,
                    item.title,
                    detail=item.plan.title,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    link=f"/training/plans/{item.plan_id}",
                )
            )
        for item in sessions.filter(plan__coach=request.user).exclude(plan__owner=request.user):
            entries.append(
                _entry(
                    "trainee_session",
                    item.id,
                    item.title,
                    detail=f"{item.plan.owner.display_name} · {item.plan.title}",
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                )
            )
        clubs = []
        if profile:
            member_of = Membership.objects.active().filter(user=request.user).values("organization")
            clubs = list(profile.organizations.filter(pk__in=member_of))
        for item in sessions.filter(plan__organization__in=clubs):
            entries.append(
                _entry(
                    "club_session",
                    item.id,
                    item.title,
                    detail=f"{item.plan.organization.name} · {item.plan.title}",
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    link=f"/training/club-plans/{item.plan_id}",
                )
            )
        tournaments = Tournament.objects.filter(
            organization__in=clubs,
            status__in=[Tournament.Status.PUBLISHED, Tournament.Status.IN_PROGRESS],
            starts_on__lte=last,
            ends_on__gte=first,
        ).select_related("organization")
        for cup in tournaments:
            entries.append(
                _entry(
                    "tournament",
                    cup.id,
                    cup.name,
                    detail=cup.organization.name,
                    starts_on=cup.starts_on,
                    ends_on=cup.ends_on,
                    status=cup.status,
                    link=f"/tournaments/{cup.id}",
                )
            )

        def when(entry):
            if entry["starts_at"]:
                return entry["starts_at"]
            return datetime.combine(entry["starts_on"], datetime.min.time(), tz)

        return Response(CalendarEntrySerializer(sorted(entries, key=when), many=True).data)
