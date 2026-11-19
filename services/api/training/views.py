"""Training API (REQ-026, REQ-027). Personal things live under /me/ and are scoped to the requester, so
anyone else's ids are 404. Club drills live under the organization: members read them, holders of
training.manage change them."""

from django.db import transaction
from django.db.models import Max, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
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
        return Response(DrillSerializer(organization.drills.all(), many=True).data)

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


def _plans(user):
    items = PlanItem.objects.select_related("drill")
    return TrainingPlan.objects.filter(owner=user).prefetch_related(Prefetch("items", queryset=items))


class TrainingPlanViewSet(viewsets.ModelViewSet):
    """The player's own training plans with their items and progress."""

    serializer_class = TrainingPlanSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TrainingPlan.objects.none()
        return _plans(self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class PlanItemViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Items of one of the player's plans. Sessions are checked against the player's calendar; ticking an
    item off (`completed`) is all a checklist item ever does."""

    serializer_class = PlanItemSerializer
    permission_classes = [IsAuthenticated]

    def plan(self) -> TrainingPlan:
        return get_object_or_404(TrainingPlan, pk=self.kwargs["plan_pk"], owner=self.request.user)

    def _drill(self, data):
        if "drill_id" not in data:
            return
        drill_id = data.pop("drill_id")
        data["drill"] = None
        if drill_id is not None:
            data["drill"] = service.usable_drills(self.request.user).filter(pk=drill_id).first()
            if data["drill"] is None:
                raise ValidationError({"drill": "Choose one of your drills or your club's."})

    @extend_schema(request=PlanItemSerializer, responses={201: TrainingPlanSerializer})
    def create(self, request, plan_pk):
        serializer = PlanItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        completed = data.pop("completed", False)
        self._drill(data)
        if not data.get("title"):
            if not data.get("drill"):
                raise ValidationError({"title": "Give the item a title or choose a drill."})
            data["title"] = data["drill"].title
        with transaction.atomic():
            service.lock_player(request.user)
            plan = self.plan()
            if data["kind"] == PlanItem.Kind.SESSION:
                service.ensure_free(request.user, data["starts_at"], data["ends_at"])
            last = plan.items.aggregate(last=Max("order"))["last"]
            PlanItem.objects.create(
                plan=plan,
                order=0 if last is None else last + 1,
                completed_at=timezone.now() if completed else None,
                **data,
            )
        return Response(TrainingPlanSerializer(_plans(request.user).get(pk=plan.pk)).data, status=201)

    @extend_schema(request=PlanItemSerializer, responses={200: TrainingPlanSerializer})
    def partial_update(self, request, plan_pk, pk):
        with transaction.atomic():
            service.lock_player(request.user)
            plan = self.plan()
            item = get_object_or_404(plan.items.select_for_update(), pk=pk)
            serializer = PlanItemSerializer(item, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            self._drill(data)
            if "title" in data and not data["title"]:
                raise ValidationError({"title": "Give the item a title."})
            if "completed" in data:
                done = data.pop("completed")
                if done != bool(item.completed_at):
                    item.completed_at = timezone.now() if done else None
            for name, value in data.items():
                setattr(item, name, value)
            if item.kind == PlanItem.Kind.SESSION and ({"starts_at", "ends_at"} & set(data)):
                service.ensure_free(request.user, item.starts_at, item.ends_at, exclude=item)
            item.save()
        return Response(TrainingPlanSerializer(_plans(request.user).get(pk=plan.pk)).data)

    @extend_schema(responses={200: TrainingPlanSerializer})
    def destroy(self, request, plan_pk, pk):
        plan = self.plan()
        get_object_or_404(plan.items, pk=pk).delete()
        return Response(TrainingPlanSerializer(_plans(request.user).get(pk=plan.pk)).data)


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
