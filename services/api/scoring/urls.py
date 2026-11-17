from django.urls import path

from .views import ScorecardViewSet, UmpireViewSet

# Mounted under /scorecards/.
urlpatterns = [
    path("<uuid:pk>/", ScorecardViewSet.as_view({"get": "retrieve"}), name="scorecard-detail"),
    path("<uuid:pk>/events/", ScorecardViewSet.as_view({"post": "events"}), name="scorecard-events"),
    path("<uuid:pk>/confirm/", ScorecardViewSet.as_view({"post": "confirm"}), name="scorecard-confirm"),
]

# Mounted under /me/.
me_urlpatterns = [
    path("scorecards/", ScorecardViewSet.as_view({"get": "list"}), name="me-scorecards"),
]

# Mounted under /tournaments/.
tournament_urlpatterns = [
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
