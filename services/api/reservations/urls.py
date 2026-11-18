from django.urls import path

from .views import DispatchViewSet

# Mounted under /tournaments/.
urlpatterns = [
    path(
        "<uuid:tournament_pk>/tables/", DispatchViewSet.as_view({"get": "tables"}), name="tournament-tables"
    ),
    path(
        "<uuid:tournament_pk>/reservations/",
        DispatchViewSet.as_view({"get": "reservations"}),
        name="tournament-reservations",
    ),
    path(
        "<uuid:tournament_pk>/dispatch/",
        DispatchViewSet.as_view({"get": "board"}),
        name="tournament-dispatch",
    ),
    path(
        "<uuid:tournament_pk>/dispatch/auto/",
        DispatchViewSet.as_view({"post": "set_auto"}),
        name="tournament-dispatch-auto",
    ),
    path(
        "<uuid:tournament_pk>/dispatch/run/",
        DispatchViewSet.as_view({"post": "run"}),
        name="tournament-dispatch-run",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/dispatch/",
        DispatchViewSet.as_view({"post": "dispatch_match"}),
        name="tournament-event-match-dispatch",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/recall/",
        DispatchViewSet.as_view({"post": "recall"}),
        name="tournament-event-match-recall",
    ),
]
