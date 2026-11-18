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
