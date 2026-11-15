from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from core.pagination import StandardPagination, search_term

from .models import JoinRequest, Membership, Organization
from .serializers import (
    JoinRequestSerializer,
    MembershipSerializer,
    MyJoinRequestSerializer,
    OrganizationSerializer,
)


class OrganizationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Search, view and register organizations (REQ-004)."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    queryset = Organization.objects.all()

    @extend_schema(parameters=[OpenApiParameter("search", str, description="Name or town")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        term = search_term(self.request)
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
    """Join requests for one organization (REQ-004). Any signed-in player can ask to join; only
    active admins of that organization can list or decide requests (TASK-013 replaces this check
    with real permissions). Routes are mapped explicitly in urls.py."""

    serializer_class = JoinRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def require_admin(self, organization):
        if not Membership.objects.is_admin(self.request.user, organization):
            raise ApiException(
                "not_organization_admin", "Only organization admins can manage join requests.", 403
            )

    @extend_schema(responses={200: JoinRequestSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        self.require_admin(organization)
        pending = organization.join_requests.filter(status=JoinRequest.Status.PENDING).select_related("user")
        page = self.paginate_queryset(pending)
        return self.get_paginated_response(JoinRequestSerializer(page, many=True).data)

    @extend_schema(request=None, responses={201: MyJoinRequestSerializer, 200: MyJoinRequestSerializer})
    def create(self, request, organization_pk):
        organization = self.get_organization()
        if Membership.objects.active().filter(organization=organization, user=request.user).exists():
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
        with transaction.atomic():
            # Checked inside the transaction so a concurrently removed admin can't still decide.
            self.require_admin(organization)
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
                # A returning former admin rejoins as a plain member, never with old authority.
                Membership.objects.update_or_create(
                    organization=organization,
                    user=join_request.user,
                    defaults={"status": Membership.Status.ACTIVE, "role": Membership.Role.MEMBER},
                )
        return Response(JoinRequestSerializer(join_request).data)

    @extend_schema(request=None, responses={200: JoinRequestSerializer})
    def approve(self, request, organization_pk, pk):
        return self._decide(request, organization_pk, pk, JoinRequest.Status.APPROVED)

    @extend_schema(request=None, responses={200: JoinRequestSerializer})
    def reject(self, request, organization_pk, pk):
        return self._decide(request, organization_pk, pk, JoinRequest.Status.REJECTED)


class MyMembershipsView(generics.ListAPIView):
    """Organizations the signed-in player belongs to: the basis for the context switcher."""

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no user
            return Membership.objects.none()
        return Membership.objects.active().filter(user=self.request.user).select_related("organization")


class MyJoinRequestsView(generics.ListAPIView):
    """The signed-in player's own join requests (REQ-004), newest first."""

    serializer_class = MyJoinRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return JoinRequest.objects.none()
        return JoinRequest.objects.filter(user=self.request.user).order_by("-created_at")
