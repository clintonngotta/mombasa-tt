from django.urls import path

from .views import EventViewSet, OrganizationTournamentViewSet, TournamentViewSet


def action(viewset, name):
    return viewset.as_view({"post": name})


# Mounted under /tournaments/.
urlpatterns = [
    path("", TournamentViewSet.as_view({"get": "list"}), name="tournament-list"),
    path(
        "<uuid:pk>/",
        TournamentViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="tournament-detail",
    ),
    path("<uuid:pk>/publish/", action(TournamentViewSet, "publish"), name="tournament-publish"),
    path("<uuid:pk>/start/", action(TournamentViewSet, "start"), name="tournament-start"),
    path("<uuid:pk>/complete/", action(TournamentViewSet, "complete"), name="tournament-complete"),
    path("<uuid:pk>/cancel/", action(TournamentViewSet, "cancel"), name="tournament-cancel"),
    path("<uuid:pk>/history/", TournamentViewSet.as_view({"get": "history"}), name="tournament-history"),
    path("<uuid:tournament_pk>/events/", action(EventViewSet, "create"), name="tournament-events"),
    path(
        "<uuid:tournament_pk>/events/<uuid:pk>/",
        EventViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="tournament-event",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:pk>/start/",
        action(EventViewSet, "start"),
        name="tournament-event-start",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:pk>/complete/",
        action(EventViewSet, "complete"),
        name="tournament-event-complete",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:pk>/cancel/",
        action(EventViewSet, "cancel"),
        name="tournament-event-cancel",
    ),
]

# Mounted under /organizations/<organization_pk>/.
organization_urlpatterns = [
    path(
        "tournaments/",
        OrganizationTournamentViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-tournaments",
    ),
]
