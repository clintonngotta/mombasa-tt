from django.urls import path

from .views import (
    DrawViewSet,
    EntryViewSet,
    EventViewSet,
    MyEntriesViewSet,
    OrganizationTournamentViewSet,
    TournamentViewSet,
)


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
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/entries/",
        EntryViewSet.as_view({"get": "list", "post": "create"}),
        name="tournament-event-entries",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/draw/",
        DrawViewSet.as_view({"get": "retrieve"}),
        name="tournament-event-draw",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/standings/",
        DrawViewSet.as_view({"get": "standings"}),
        name="tournament-event-standings",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/draw/preview/",
        action(DrawViewSet, "preview"),
        name="tournament-event-draw-preview",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/draw/publish/",
        action(DrawViewSet, "publish"),
        name="tournament-event-draw-publish",
    ),
    *(
        path(
            f"<uuid:tournament_pk>/events/<uuid:event_pk>/entries/<uuid:pk>/{slug}/",
            action(EntryViewSet, slug.replace("-", "_")),
            name=f"tournament-event-entry-{slug}",
        )
        for slug in (
            "accept",
            "waitlist",
            "reject",
            "staff-withdraw",
            "check-in",
            "undo-check-in",
            "withdraw",
        )
    ),
]

# Mounted under /me/.
me_urlpatterns = [
    path("entries/", MyEntriesViewSet.as_view({"get": "list"}), name="me-entries"),
]

# Mounted under /organizations/<organization_pk>/.
organization_urlpatterns = [
    path(
        "tournaments/",
        OrganizationTournamentViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-tournaments",
    ),
]
