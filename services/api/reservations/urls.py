from django.urls import path

from .views import ControlViewSet, DispatchViewSet

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
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/call/",
        ControlViewSet.as_view({"post": "call"}),
        name="tournament-event-match-call",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/report/",
        ControlViewSet.as_view({"post": "report"}),
        name="tournament-event-match-report",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/move/",
        ControlViewSet.as_view({"post": "move"}),
        name="tournament-event-match-move",
    ),
    path(
        "<uuid:tournament_pk>/tables/<uuid:table_pk>/block/",
        ControlViewSet.as_view({"post": "block"}),
        name="tournament-table-block",
    ),
    path(
        "<uuid:tournament_pk>/tables/<uuid:table_pk>/unblock/",
        ControlViewSet.as_view({"post": "unblock"}),
        name="tournament-table-unblock",
    ),
    path(
        "<uuid:tournament_pk>/check-in-desk/",
        ControlViewSet.as_view({"get": "desk"}),
        name="tournament-check-in-desk",
    ),
    path(
        "<uuid:tournament_pk>/match-day-log/",
        ControlViewSet.as_view({"get": "log"}),
        name="tournament-match-day-log",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/recall/",
        DispatchViewSet.as_view({"post": "recall"}),
        name="tournament-event-match-recall",
    ),
]
