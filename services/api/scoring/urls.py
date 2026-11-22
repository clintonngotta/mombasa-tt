from django.urls import path

from .views import LiveViewSet, ScorecardViewSet, ScoringOverviewViewSet, UmpireViewSet

# Mounted under /scorecards/.
urlpatterns = [
    path("<uuid:pk>/", ScorecardViewSet.as_view({"get": "retrieve"}), name="scorecard-detail"),
    path("<uuid:pk>/events/", ScorecardViewSet.as_view({"post": "events"}), name="scorecard-events"),
    path("<uuid:pk>/next/", ScorecardViewSet.as_view({"get": "next"}), name="scorecard-next"),
    path("<uuid:pk>/confirm/", ScorecardViewSet.as_view({"post": "confirm"}), name="scorecard-confirm"),
    path("<uuid:pk>/device/", ScorecardViewSet.as_view({"post": "device"}), name="scorecard-device"),
    path("<uuid:pk>/conflicts/", ScorecardViewSet.as_view({"post": "conflicts"}), name="scorecard-conflicts"),
]

# Mounted under /me/.
me_urlpatterns = [
    path("scorecards/", ScorecardViewSet.as_view({"get": "list"}), name="me-scorecards"),
]

# Mounted under /tournaments/.
tournament_urlpatterns = [
    path("<uuid:tournament_pk>/live/", LiveViewSet.as_view({"get": "list"}), name="tournament-live"),
    path(
        "<uuid:tournament_pk>/scoring/",
        ScoringOverviewViewSet.as_view({"get": "retrieve"}),
        name="tournament-scoring",
    ),
    path(
        "<uuid:tournament_pk>/scoring/conflicts/<uuid:pk>/resolve/",
        ScoringOverviewViewSet.as_view({"post": "resolve"}),
        name="tournament-scoring-conflict-resolve",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/umpires/",
        UmpireViewSet.as_view({"get": "list"}),
        name="tournament-event-umpires",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/umpire/",
        UmpireViewSet.as_view({"post": "assign"}),
        name="tournament-event-match-umpire",
    ),
]
