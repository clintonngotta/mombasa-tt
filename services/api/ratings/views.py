from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from organizations.models import Membership, Organization
from profiles.models import PlayerProfile

from . import service
from .models import Discipline, Rating, RatingEvent
from .serializers import PlayerRatingsSerializer, RankingSerializer

FORM_LENGTH = 5
RANKING_LIMIT = 200
HISTORY_LIMIT = 50


def _discipline(request) -> str:
    asked = request.query_params.get("discipline", Discipline.SINGLES)
    if asked not in Discipline.values:
        raise ApiException("unknown_discipline", "Choose singles or doubles.", 400)
    return asked


def _listed(user_ids) -> set:
    """Those of the players who have a page in the directory (REQ-006)."""
    listed = PlayerProfile.objects.filter(user_id__in=user_ids, directory_opt_in=True, user__is_active=True)
    return set(listed.values_list("user_id", flat=True))


def _form(discipline: str, user_ids) -> dict:
    """Each player's latest rated matches, newest first, and the latest delta."""
    found: dict = {user_id: [] for user_id in user_ids}
    events = RatingEvent.objects.filter(discipline=discipline, user_id__in=user_ids).order_by(
        "-accepted_at", "-subject_id"
    )
    for user_id, won, delta in events.values_list("user_id", "won", "delta"):
        if len(found[user_id]) < FORM_LENGTH:
            found[user_id].append(("W" if won else "L", delta))
    return found


def _ranks(discipline: str) -> dict:
    """Everybody's platform rank: players with the same rating share one."""
    ranks, rank, last = {}, 0, None
    rated = Rating.objects.filter(discipline=discipline, played__gt=0, user__is_active=True)
    for place, (user_id, rating) in enumerate(rated.order_by("-rating").values_list("user_id", "rating"), 1):
        if rating != last:
            rank, last = place, rating
        ranks[user_id] = rank
    return ranks


class RankingView(APIView):
    """The ranking of one discipline: over the whole platform, or among one club's members."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("discipline", str, enum=Discipline.values, description="Default singles."),
            OpenApiParameter("organization", str, description="A club you belong to: rank its members only."),
        ],
        responses={200: RankingSerializer},
    )
    def get(self, request):
        discipline = _discipline(request)
        rated = Rating.objects.filter(discipline=discipline, played__gt=0, user__is_active=True)
        organization = None
        if request.query_params.get("organization"):
            organization = get_object_or_404(Organization, pk=request.query_params["organization"])
            members = Membership.objects.active().filter(organization=organization)
            if not members.filter(user=request.user).exists():
                raise ApiException("permission_denied", "Only the club's members see its ranking.", 403)
            rated = rated.filter(user_id__in=members.values("user_id"))
        count = rated.count()
        top = list(rated.select_related("user").order_by("-rating", "user__display_name")[:RANKING_LIMIT])
        user_ids = [rating.user_id for rating in top]
        form, listed = _form(discipline, user_ids), _listed(user_ids)
        clubs: dict = {}
        active = Membership.objects.active().filter(user_id__in=user_ids).select_related("organization")
        for membership in active.order_by("organization__name"):
            clubs.setdefault(membership.user_id, []).append(membership.organization.name)
        rows, rank, last = [], 0, None
        for place, rating in enumerate(top, 1):
            if rating.rating != last:  # a rank within the scope shown: club ranks count members only
                rank, last = place, rating.rating
            recent = form[rating.user_id]
            rows.append(
                {
                    "rank": rank,
                    "user_id": rating.user_id,
                    "display_name": rating.user.display_name,
                    "clubs": clubs.get(rating.user_id, []),
                    "listed": rating.user_id in listed,
                    "is_me": rating.user_id == request.user.id,
                    "rating": rating.rating,
                    "played": rating.played,
                    "won": rating.won,
                    "form": [letter for letter, _ in recent],
                    "last_delta": recent[0][1] if recent else None,
                }
            )
        shown = {
            "discipline": discipline,
            "scope": "club" if organization else "platform",
            "organization_id": organization.id if organization else None,
            "organization_name": organization.name if organization else "",
            "processing": service.pending(discipline),
            "count": count,
            "rows": rows,
        }
        return Response(RankingSerializer(shown).data)


class PlayerRatingsView(APIView):
    """One player's ratings in both disciplines and the rating changes of one of them, newest first.
    Ratings come from competition results, which signed-in players can already read in the draws; a
    player who has none and no page in the directory is not found."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("discipline", str, enum=Discipline.values, description="Default singles."),
            OpenApiParameter("result", str, enum=["all", "won", "lost"], description="Default all."),
        ],
        responses={200: PlayerRatingsSerializer},
    )
    def get(self, request, pk):
        discipline = _discipline(request)
        which = request.query_params.get("result", "all")
        if which not in {"all", "won", "lost"}:
            raise ApiException("unknown_filter", "Choose all, won or lost.", 400)
        player = get_object_or_404(get_user_model(), pk=pk, is_active=True)
        known = player.id == request.user.id or RatingEvent.objects.filter(user=player).exists()
        if not known and not _listed([player.id]):
            raise ApiException("not_found", "Not found.", 404)
        summaries = []
        for one in Discipline.values:
            rating = Rating.objects.filter(user=player, discipline=one, played__gt=0).first()
            ranks = _ranks(one)
            summaries.append(
                {
                    "discipline": one,
                    "rating": rating.rating if rating else None,
                    "played": rating.played if rating else 0,
                    "won": rating.won if rating else 0,
                    "rank": ranks.get(player.id),
                    "ranked": len(ranks),
                    "form": [letter for letter, _ in _form(one, [player.id])[player.id]],
                }
            )
        events = RatingEvent.objects.filter(user=player, discipline=discipline)
        if which != "all":
            events = events.filter(won=which == "won")
        shown = {
            "user_id": player.id,
            "display_name": player.display_name,
            "processing": service.pending(),
            "summaries": summaries,
            "discipline": discipline,
            "result": which,
            "count": events.count(),
            "history": _history(events.order_by("-accepted_at", "-subject_id")[:HISTORY_LIMIT]),
        }
        return Response(PlayerRatingsSerializer(shown).data)


def _history(events) -> list[dict]:
    events = list(events.select_related("result", "match__draw__event__tournament", "rubber"))
    # Who else was in each match: the other rating events of the same match or rubber.
    others: dict = {}
    same = RatingEvent.objects.filter(subject_id__in=[event.subject_id for event in events])
    for other in same.select_related("user").order_by("side", "user__display_name"):
        others.setdefault((other.discipline, other.subject_id), []).append(other)
    history = []
    for event in events:
        around = [o for o in others[(event.discipline, event.subject_id)] if o.user_id != event.user_id]
        tournament = event.match.draw.event.tournament
        games = event.result.games
        history.append(
            {
                "id": event.id,
                "discipline": event.discipline,
                "at": event.accepted_at,
                "won": event.won,
                "before": event.before,
                "after": event.after,
                "delta": event.delta,
                "expected": event.expected,
                "own": event.own,
                "opponent": event.opponent,
                "partner": next((o.user.display_name for o in around if o.side == event.side), ""),
                "opponents": [o.user.display_name for o in around if o.side != event.side],
                "games": games if event.side == "a" else [[b, a] for a, b in games],
                "tournament_id": tournament.id,
                "tournament_name": tournament.name,
                "event_id": event.match.draw.event_id,
                "event_name": event.match.draw.event.name,
                "match_id": event.match_id,
                "rubber": event.rubber.position if event.rubber_id else None,
                "corrected": event.result.version > 1,
            }
        )
    return history
