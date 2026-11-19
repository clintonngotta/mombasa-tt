"""Soda games (REQ-040, TASK-076)."""

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from organizations.access import require_membership, require_permission
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import service
from .models import Challenge, Policy
from .serializers import (
    AcceptSerializer,
    ChallengeSerializer,
    CounterSerializer,
    DisputeSerializer,
    MySodaSettingsSerializer,
    PolicySerializer,
    RecordSerializer,
    SharedChallengeSerializer,
    ShareSerializer,
)


class ChallengeViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """The signed-in player's soda games, made or received. Nobody else reaches them here."""

    serializer_class = ChallengeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Challenge.objects.none()
        me = self.request.user
        return (
            Challenge.objects.filter(Q(challenger=me) | Q(challenged=me))
            .select_related("challenger", "challenged", "result")
            .order_by("-created_at", "-id")
        )

    def _reply(self, challenge, code=status.HTTP_200_OK):
        fresh = self.get_queryset().get(pk=challenge.pk)
        shown = service.stakes_allowed(fresh.challenger, fresh.challenged)
        context = {**self.get_serializer_context(), "stakes_shown": shown}
        return Response(ChallengeSerializer(fresh, context=context).data, status=code)

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        data = []
        for challenge in page:
            shown = service.stakes_allowed(challenge.challenger, challenge.challenged)
            context = {**self.get_serializer_context(), "stakes_shown": shown}
            data.append(ChallengeSerializer(challenge, context=context).data)
        return self.get_paginated_response(data)

    def retrieve(self, request, *args, **kwargs):
        return self._reply(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        challenged = get_object_or_404(get_user_model(), pk=data.pop("challenged_id"))
        staked = data.get("stake_minor") is not None or bool(data.get("stake_note"))
        service.check_new(request.user, challenged, staked)
        challenge = Challenge.objects.create(challenger=request.user, challenged=challenged, **data)
        return self._reply(challenge, status.HTTP_201_CREATED)

    @extend_schema(request=AcceptSerializer, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def accept(self, request, *args, **kwargs):
        """The challenged player accepts, matching the stake or not; or the challenger takes the time
        the challenged player proposed."""
        body = AcceptSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._reply(
            service.accept(self.get_object(), request.user, body.validated_data["match_stake"])
        )

    @extend_schema(request=CounterSerializer, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def counter(self, request, *args, **kwargs):
        """The challenged player proposes another time."""
        body = CounterSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._reply(service.counter(self.get_object(), request.user, body.validated_data["play_at"]))

    @extend_schema(request=None, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def decline(self, request, *args, **kwargs):
        return self._reply(service.decline(self.get_object(), request.user))

    @extend_schema(request=None, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def withdraw(self, request, *args, **kwargs):
        """The challenger withdraws before the challenge is accepted."""
        return self._reply(service.withdraw(self.get_object(), request.user))

    @extend_schema(request=RecordSerializer, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def result(self, request, *args, **kwargs):
        """Record the games. The other player then confirms or disputes."""
        body = RecordSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        challenge = self.get_object()
        service.record(challenge, request.user, body.validated_data["games"])
        return self._reply(challenge)

    @extend_schema(request=None, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def confirm(self, request, *args, **kwargs):
        challenge = self.get_object()
        service.confirm(challenge, request.user)
        return self._reply(challenge)

    @extend_schema(request=DisputeSerializer, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def dispute(self, request, *args, **kwargs):
        """Disagree with the recorded games: nothing is owed until it's recorded again and confirmed."""
        body = DisputeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        challenge = self.get_object()
        service.dispute(challenge, request.user, body.validated_data["reason"])
        return self._reply(challenge)

    @extend_schema(request=None, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def settle(self, request, *args, **kwargs):
        """The winner marks the pledge honoured. No money passes through Coast TT."""
        challenge = self.get_object()
        service.settle(challenge, request.user)
        return self._reply(challenge)

    @extend_schema(request=ShareSerializer, responses={200: ChallengeSerializer})
    @action(detail=True, methods=["post"])
    def share(self, request, *args, **kwargs):
        """Let club members see this challenge and its result. Shown only when both players share."""
        body = ShareSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        challenge = self.get_object()
        field = "challenger_shares" if challenge.challenger_id == request.user.pk else "challenged_shares"
        setattr(challenge, field, body.validated_data["share"])
        challenge.save(update_fields=[field])
        return self._reply(challenge)


class MySodaSettingsView(APIView):
    """Whether soda games and stakes are available to the signed-in player."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MySodaSettingsSerializer})
    def get(self, request):
        data = {
            "stakes_available": service.stakes_allowed(request.user),
            "games_enabled": service.games_allowed(request.user),
        }
        return Response(MySodaSettingsSerializer(data).data)


class ClubChallengesView(APIView):
    """Soda games of the club's members that both players chose to share: names, time and result only."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SharedChallengeSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_membership(request.user, organization)
        members = Membership.objects.active().filter(organization=organization).values("user_id")
        shared = (
            Challenge.objects.filter(challenger_shares=True, challenged_shares=True)
            .filter(Q(challenger__in=members) | Q(challenged__in=members))
            .exclude(status__in=[Challenge.Status.DECLINED, Challenge.Status.WITHDRAWN])
            .select_related("challenger", "challenged", "result")
            .order_by("-created_at")[:50]
        )
        return Response(SharedChallengeSerializer(shared, many=True).data)


class SodaPolicyView(APIView):
    """An organization's switches for its members' soda games. Changing them needs roles.manage."""

    permission_classes = [IsAuthenticated]

    def _reply(self, organization):
        policy = Policy.objects.filter(organization=organization).first()
        data = {
            "games_enabled": policy.games_enabled if policy else True,
            "stakes_enabled": policy.stakes_enabled if policy else True,
            "stakes_available": service.gate_open(),
        }
        return Response(PolicySerializer(data).data)

    @extend_schema(responses={200: PolicySerializer})
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_membership(request.user, organization)
        return self._reply(organization)

    @extend_schema(request=PolicySerializer, responses={200: PolicySerializer})
    def put(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, Permission.ROLES_MANAGE)
        body = PolicySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        Policy.objects.update_or_create(
            organization=organization,
            defaults={
                "games_enabled": body.validated_data["games_enabled"],
                "stakes_enabled": body.validated_data["stakes_enabled"],
            },
        )
        return self._reply(organization)
