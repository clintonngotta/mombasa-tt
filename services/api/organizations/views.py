from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException

from .models import JoinRequest, Membership, Organization, is_admin
from .serializers import (
    JoinRequestSerializer,
    MembershipSerializer,
    MyJoinRequestSerializer,
    OrganizationSerializer,
)


class OrganizationPagination(PageNumberPagination):
    page_size = 20


class OrganizationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Search, view and register organizations (REQ-004)."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = OrganizationPagination
    queryset = Organization.objects.all()

    @extend_schema(parameters=[OpenApiParameter("search", str, description="Name or town")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        term = self.request.query_params.get("search", "").strip()
        if term:
            queryset = queryset.filter(Q(name__icontains=term) | Q(town__icontains=term))
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        organization = serializer.save(created_by=self.request.user)
        # The creator becomes the first admin.
        Membership.objects.create(
            organization=organization, user=self.request.user, role=Membership.Role.ADMIN
        )


class JoinRequestViewSet(viewsets.GenericViewSet):
    """`/organizations/{id}/join-requests/`. Any signed-in player can ask to join. Only active
    admins of that organization can list or decide requests (TASK-013 replaces this check with
    real permissions)."""

    serializer_class = JoinRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def require_admin(self, organization):
        if not is_admin(self.request.user, organization):
            raise PermissionDenied("Only organization admins can manage join requests.")

    @extend_schema(responses={200: JoinRequestSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        self.require_admin(organization)
        pending = organization.join_requests.filter(status=JoinRequest.Status.PENDING).select_related("user")
        return Response(JoinRequestSerializer(pending, many=True).data)

    @extend_schema(request=None, responses={201: MyJoinRequestSerializer, 200: MyJoinRequestSerializer})
    def create(self, request, organization_pk):
        organization = self.get_organization()
        if Membership.objects.filter(
            organization=organization, user=request.user, status=Membership.Status.ACTIVE
        ).exists():
            raise ApiException("already_member", "You're already a member of this organization.", 409)

        existing = JoinRequest.objects.filter(
            organization=organization, user=request.user, status=JoinRequest.Status.PENDING
        ).first()
        if existing:  # asking twice is harmless
            return Response(MyJoinRequestSerializer(existing).data)
        try:
            with transaction.atomic():
                join_request = JoinRequest.objects.create(organization=organization, user=request.user)
        except IntegrityError:  # a concurrent duplicate won the race
            join_request = JoinRequest.objects.get(
                organization=organization, user=request.user, status=JoinRequest.Status.PENDING
            )
            return Response(MyJoinRequestSerializer(join_request).data)
        return Response(MyJoinRequestSerializer(join_request).data, status=status.HTTP_201_CREATED)

    def _decide(self, request, organization_pk, pk, outcome):
        organization = self.get_organization()
        self.require_admin(organization)
        with transaction.atomic():
            join_request = get_object_or_404(
                JoinRequest.objects.select_for_update(), pk=pk, organization=organization
            )
            if join_request.status != JoinRequest.Status.PENDING:
                raise ApiException("already_decided", "This request has already been decided.", 409)
            join_request.status = outcome
            join_request.decided_at = timezone.now()
            join_request.decided_by = request.user
            join_request.save(update_fields=["status", "decided_at", "decided_by"])
            if outcome == JoinRequest.Status.APPROVED:
                Membership.objects.update_or_create(
                    organization=organization,
                    user=join_request.user,
                    defaults={"status": Membership.Status.ACTIVE},
                    create_defaults={"role": Membership.Role.MEMBER},
                )
        return Response(JoinRequestSerializer(join_request).data)

    @extend_schema(request=None, responses={200: JoinRequestSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request, organization_pk, pk):
        return self._decide(request, organization_pk, pk, JoinRequest.Status.APPROVED)

    @extend_schema(request=None, responses={200: JoinRequestSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request, organization_pk, pk):
        return self._decide(request, organization_pk, pk, JoinRequest.Status.REJECTED)


class MyMembershipsView(generics.ListAPIView):
    """Organizations the signed-in player belongs to: the basis for the context switcher."""

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return Membership.objects.filter(
            user=self.request.user, status=Membership.Status.ACTIVE
        ).select_related("organization")


class MyJoinRequestsView(generics.ListAPIView):
    serializer_class = MyJoinRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return JoinRequest.objects.filter(user=self.request.user).order_by("-created_at")
