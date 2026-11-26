"""Training API (REQ-026, REQ-027).

Personal things live under /me/ and are scoped to the requester, so anyone else's ids are 404. The drill
library at /drills/ is every drill the player may use: the standard library, their own, and those of clubs
they are an active member of. A club's drills and plans live under the organization: members read them,
holders of training.manage write them. Club plans are a programme for a day, a week or longer; their
sessions are the club's timetable and reserve nobody's time (table reservations come with TASK-044).
"""

from django.db import transaction
from django.db.models import Max, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from organizations.access import require_membership, require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from . import service
from .models import Drill, Equipment, PlanItem, TrainingPlan
from .serializers import (
    DrillRecommendationSerializer,
    DrillSerializer,
    EquipmentSerializer,
    PlanItemSerializer,
    TrainingPlanSerializer,
    UpcomingSessionSerializer,
)

TRAINING = Permission.TRAINING_MANAGE


class EquipmentView(APIView):
    """GET/PUT /me/equipment/: the player's own equipment, private to them."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: EquipmentSerializer})
    def get(self, request):
        equipment = Equipment.objects.filter(user=request.user).first() or Equipment(user=request.user)
        return Response(EquipmentSerializer(equipment).data)

    @extend_schema(request=EquipmentSerializer, responses={200: EquipmentSerializer})
    def put(self, request):
        equipment, _ = Equipment.objects.get_or_create(user=request.user)
        serializer = EquipmentSerializer(equipment, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DrillLibraryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """GET /drills/: every drill the player may use, standard ones first; GET /drills/{id}/ one of them."""

    serializer_class = DrillSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Drill.objects.none()
        # Opening one drill also reaches those a coach put in the player's plan; the list is what they use.
        visible = service.readable_drills if self.action == "retrieve" else service.usable_drills
        drills = visible(self.request.user).select_related("organization")
        params = self.request.query_params
        for name in ("category", "level"):
            if params.get(name):
                drills = drills.filter(**{name: params[name]})
        library = params.get("library")
        if library == "standard":
            drills = drills.filter(owner__isnull=True, organization__isnull=True)
        elif library == "personal":
            drills = drills.filter(owner=self.request.user)
        elif library == "club":
            drills = drills.filter(organization__isnull=False)
        if params.get("search"):
            term = params["search"].strip()[:80]
            drills = drills.filter(Q(title__icontains=term) | Q(focus__icontains=term))
        return drills.order_by("organization", "owner", "title")

    @extend_schema(
        parameters=[
            OpenApiParameter("category", str),
            OpenApiParameter("level", str),
            OpenApiParameter("library", str, enum=["standard", "personal", "club"]),
            OpenApiParameter("search", str, description="Title or focus"),
        ]
    )
    def list(self, request, *args, **kwargs):
        return Response(DrillSerializer(self.get_queryset()[:300], many=True).data)


class MyDrillViewSet(viewsets.ModelViewSet):
    """The player's personal drill library, private to them."""

    serializer_class = DrillSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Drill.objects.none()
        return Drill.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, created_by=self.request.user)


class ClubDrillViewSet(viewsets.GenericViewSet):
    """A club's drill library: every active member reads it; training staff add, change and delete."""

    serializer_class = DrillSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    @extend_schema(responses={200: DrillSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.organization()
        require_membership(request.user, organization)
        return Response(DrillSerializer(organization.drills.select_related("organization"), many=True).data)

    @extend_schema(request=DrillSerializer, responses={201: DrillSerializer})
    def create(self, request, organization_pk):
        organization = self.organization()
        require_permission(request.user, organization, TRAINING)
        serializer = DrillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        drill = serializer.save(organization=organization, created_by=request.user)
        return Response(DrillSerializer(drill).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=DrillSerializer, responses={200: DrillSerializer})
    def partial_update(self, request, organization_pk, pk):
        organization = self.organization()
        require_permission(request.user, organization, TRAINING)
        drill = get_object_or_404(organization.drills, pk=pk)
        serializer = DrillSerializer(drill, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(DrillSerializer(serializer.save()).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, organization_pk, pk):
        organization = self.organization()
        require_permission(request.user, organization, TRAINING)
        get_object_or_404(organization.drills, pk=pk).delete()  # plans keep the item and its title
        return Response(status=status.HTTP_204_NO_CONTENT)


def with_items(plans):
    return plans.prefetch_related(Prefetch("items", queryset=PlanItem.objects.select_related("drill")))


def recommendations_for(plan: TrainingPlan, drills) -> Response:
    """Drills for the plan's goal skills that aren't in the plan yet."""
    used = plan.items.exclude(drill=None).values_list("drill", flat=True)
    found = service.recommend(drills.select_related("organization"), plan.goal_skills, exclude=used)
    return Response(DrillRecommendationSerializer(found, many=True).data)


class TrainingPlanViewSet(viewsets.ModelViewSet):
    """The player's own training plans with their items and progress."""

    serializer_class = TrainingPlanSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TrainingPlan.objects.none()
        return with_items(TrainingPlan.objects.filter(owner=self.request.user))

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, created_by=self.request.user)

    @extend_schema(responses={200: DrillRecommendationSerializer(many=True)})
    @action(detail=True)
    def recommendations(self, request, pk=None):
        return recommendations_for(self.get_object(), service.usable_drills(request.user))


class ClubTrainingPlanViewSet(viewsets.GenericViewSet):
    """A club's training plans for a day, a week, a month or any dates: members read them, newest period
    first; training staff create, change and delete them."""

    serializer_class = TrainingPlanSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def plans(self, organization):
        return with_items(organization.training_plans.order_by("-starts_on", "-created_at"))

    @extend_schema(responses={200: TrainingPlanSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.organization()
        require_membership(request.user, organization)
        page = self.paginate_queryset(self.plans(organization))
        return self.get_paginated_response(TrainingPlanSerializer(page, many=True).data)

    @extend_schema(responses={200: TrainingPlanSerializer})
    def retrieve(self, request, organization_pk, pk):
        organization = self.organization()
        require_membership(request.user, organization)
        return Response(TrainingPlanSerializer(get_object_or_404(self.plans(organization), pk=pk)).data)

    @extend_schema(responses={200: DrillRecommendationSerializer(many=True)})
    def recommendations(self, request, organization_pk, pk):
        """For the club's training staff building the plan: standard drills and the club's own."""
        organization = self.organization()
        require_permission(request.user, organization, TRAINING)
        plan = get_object_or_404(organization.training_plans, pk=pk)
        return recommendations_for(plan, club_drills(organization.pk))

    @extend_schema(request=TrainingPlanSerializer, responses={201: TrainingPlanSerializer})
    def create(self, request, organization_pk):
        organization = self.organization()
        require_permission(request.user, organization, TRAINING)
        serializer = TrainingPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save(organization=organization, created_by=request.user)
        return Response(TrainingPlanSerializer(plan).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=TrainingPlanSerializer, responses={200: TrainingPlanSerializer})
    def partial_update(self, request, organization_pk, pk):
        organization = self.organization()
        require_permission(request.user, organization, TRAINING)
        plan = get_object_or_404(self.plans(organization), pk=pk)
        serializer = TrainingPlanSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(TrainingPlanSerializer(get_object_or_404(self.plans(organization), pk=pk)).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, organization_pk, pk):
        organization = self.organization()
        require_permission(request.user, organization, TRAINING)
        get_object_or_404(organization.training_plans, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanItemsBase(viewsets.GenericViewSet):
    """Adding, changing, ticking off and removing the items of a plan. Each answer is the whole plan."""

    serializer_class = PlanItemSerializer
    permission_classes = [IsAuthenticated]

    def plan(self) -> TrainingPlan:
        """The plan, after checking the caller may write it. Called inside the transaction."""
        raise NotImplementedError

    def drills(self):
        """Drills this plan may refer to."""
        raise NotImplementedError

    def calendar_owner(self):
        """Whose calendar sessions are checked against, or None when sessions reserve nobody's time."""
        return None

    def _lock(self):
        owner = self.calendar_owner()
        if owner is not None:
            service.lock_player(owner)

    def _activities(self, data):
        """Check each activity's drill is one this plan may use, fill blank titles from it and store ids
        as text."""
        if "activities" not in data:
            return
        wanted = {a["drill"] for a in data["activities"] if a.get("drill")}
        found = {drill.id: drill for drill in self.drills().filter(pk__in=wanted)}
        if wanted - set(found):
            raise ValidationError({"activities": "Choose drills from the library."})
        cleaned = []
        for activity in data["activities"]:
            drill = found.get(activity.get("drill"))
            title = activity.get("title") or (drill.title if drill else "")
            if not title:
                raise ValidationError({"activities": "Give each activity a title or a drill."})
            cleaned.append(
                {
                    "phase": activity["phase"],
                    "title": title,
                    "minutes": activity.get("minutes"),
                    "drill": str(drill.id) if drill else None,
                }
            )
        data["activities"] = cleaned

    def _drill(self, data):
        if "drill_id" not in data:
            return
        drill_id = data.pop("drill_id")
        data["drill"] = None
        if drill_id is not None:
            data["drill"] = self.drills().filter(pk=drill_id).first()
            if data["drill"] is None:
                raise ValidationError({"drill": "Choose a drill from the library."})

    def _reply(self, plan, code=status.HTTP_200_OK):
        return Response(
            TrainingPlanSerializer(with_items(TrainingPlan.objects).get(pk=plan.pk)).data, status=code
        )

    @extend_schema(request=PlanItemSerializer, responses={201: TrainingPlanSerializer})
    def create(self, request, **kwargs):
        serializer = PlanItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        completed = data.pop("completed", False)
        with transaction.atomic():
            self._lock()
            plan = self.plan()
            self._drill(data)
            self._activities(data)
            if not data.get("title"):
                if not data.get("drill"):
                    raise ValidationError({"title": "Give the item a title or choose a drill."})
                data["title"] = data["drill"].title
            owner = self.calendar_owner()
            if owner is not None and data["kind"] == PlanItem.Kind.SESSION:
                service.ensure_free(owner, data["starts_at"], data["ends_at"], with_coach=plan.coach)
            last = plan.items.aggregate(last=Max("order"))["last"]
            PlanItem.objects.create(
                plan=plan,
                order=0 if last is None else last + 1,
                completed_at=timezone.now() if completed else None,
                **data,
            )
        return self._reply(plan, status.HTTP_201_CREATED)

    @extend_schema(request=PlanItemSerializer, responses={200: TrainingPlanSerializer})
    def partial_update(self, request, pk, **kwargs):
        with transaction.atomic():
            self._lock()
            plan = self.plan()
            item = get_object_or_404(plan.items.select_for_update(), pk=pk)
            serializer = PlanItemSerializer(item, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            self._drill(data)
            self._activities(data)
            if "title" in data and not data["title"]:
                raise ValidationError({"title": "Give the item a title."})
            if "completed" in data:
                done = data.pop("completed")
                if done != bool(item.completed_at):
                    item.completed_at = timezone.now() if done else None
            for name, value in data.items():
                setattr(item, name, value)
            owner = self.calendar_owner()
            if (
                owner is not None
                and item.kind == PlanItem.Kind.SESSION
                and ({"starts_at", "ends_at"} & set(data))
            ):
                service.ensure_free(owner, item.starts_at, item.ends_at, exclude=item, with_coach=plan.coach)
            item.save()
        return self._reply(plan)

    @extend_schema(responses={200: TrainingPlanSerializer})
    def destroy(self, request, pk, **kwargs):
        with transaction.atomic():
            plan = self.plan()
            get_object_or_404(plan.items, pk=pk).delete()
        return self._reply(plan)


class PlanItemViewSet(PlanItemsBase):
    """Items of one of the player's own plans. Sessions are checked against the player's calendar;
    ticking an item off (`completed`) is all a checklist item ever does."""

    def plan(self):
        return get_object_or_404(TrainingPlan, pk=self.kwargs["plan_pk"], owner=self.request.user)

    def drills(self):
        return service.usable_drills(self.request.user)

    def calendar_owner(self):
        return self.request.user


class ClubPlanItemViewSet(PlanItemsBase):
    """Items of a club plan, for its training staff. Drills come from the standard library and the club's."""

    def organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def plan(self):
        organization = self.organization()
        require_permission(self.request.user, organization, TRAINING)
        return get_object_or_404(organization.training_plans, pk=self.kwargs["plan_pk"])

    def drills(self):
        return club_drills(self.kwargs["organization_pk"])


def club_drills(organization_id):
    """What a club plan may use: the standard library and the club's own drills."""
    return Drill.objects.filter(
        Q(owner__isnull=True, organization__isnull=True) | Q(organization=organization_id)
    )


class UpcomingSessionsView(APIView):
    """GET /me/training-sessions/: the player's sessions that haven't ended yet, soonest first."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UpcomingSessionSerializer(many=True)})
    def get(self, request):
        sessions = (
            PlanItem.objects.filter(
                plan__owner=request.user, kind=PlanItem.Kind.SESSION, ends_at__gte=timezone.now()
            )
            .select_related("plan")
            .order_by("starts_at")[:20]
        )
        return Response(UpcomingSessionSerializer(sessions, many=True).data)
