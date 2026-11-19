from django.urls import path

from .result_views import ResultViewSet
from .schedule_views import ScheduleSessionViewSet, ScheduleViewSet
from .streams import ReportStreamView, StreamsView, StreamView
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
    path("<uuid:tournament_pk>/streams/", StreamsView.as_view(), name="tournament-streams"),
    path("<uuid:tournament_pk>/streams/<uuid:pk>/", StreamView.as_view(), name="tournament-stream"),
    path(
        "<uuid:tournament_pk>/streams/<uuid:pk>/report/",
        ReportStreamView.as_view(),
        name="tournament-stream-report",
    ),
    path(
        "awaiting-approval/",
        TournamentViewSet.as_view({"get": "awaiting_approval"}),
        name="tournament-awaiting-approval",
    ),
    path(
        "<uuid:tournament_pk>/schedule/",
        ScheduleViewSet.as_view({"get": "retrieve", "put": "update"}),
        name="tournament-schedule",
    ),
    path(
        "<uuid:tournament_pk>/schedule/recommend/",
        action(ScheduleViewSet, "recommend"),
        name="tournament-schedule-recommend",
    ),
    path(
        "<uuid:tournament_pk>/schedule/check/",
        action(ScheduleViewSet, "check_plan"),
        name="tournament-schedule-check",
    ),
    path(
        "<uuid:tournament_pk>/schedule/publish/",
        action(ScheduleViewSet, "publish"),
        name="tournament-schedule-publish",
    ),
    path(
        "<uuid:tournament_pk>/schedule/delay/",
        action(ScheduleViewSet, "delay"),
        name="tournament-schedule-delay",
    ),
    path(
        "<uuid:tournament_pk>/schedule/versions/",
        ScheduleViewSet.as_view({"get": "versions"}),
        name="tournament-schedule-versions",
    ),
    path(
        "<uuid:tournament_pk>/schedule/versions/<int:number>/",
        ScheduleViewSet.as_view({"get": "version"}),
        name="tournament-schedule-version",
    ),
    path(
        "<uuid:tournament_pk>/schedule/sessions/",
        ScheduleSessionViewSet.as_view({"get": "list", "post": "create"}),
        name="tournament-schedule-sessions",
    ),
    path(
        "<uuid:tournament_pk>/schedule/sessions/<uuid:pk>/",
        ScheduleSessionViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="tournament-schedule-session",
    ),
    path(
        "<uuid:pk>/",
        TournamentViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="tournament-detail",
    ),
    path("<uuid:pk>/publish/", action(TournamentViewSet, "publish"), name="tournament-publish"),
    path(
        "<uuid:pk>/approval/request/",
        action(TournamentViewSet, "request_approval"),
        name="tournament-request-approval",
    ),
    path(
        "<uuid:pk>/approval/reject/",
        action(TournamentViewSet, "reject_approval"),
        name="tournament-reject-approval",
    ),
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
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/",
        DrawViewSet.as_view({"get": "match"}),
        name="tournament-event-match",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/result/",
        ResultViewSet.as_view({"post": "enter"}),
        name="tournament-event-match-result",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/result/correct/",
        ResultViewSet.as_view({"post": "correct"}),
        name="tournament-event-match-result-correct",
    ),
    path(
        "<uuid:tournament_pk>/corrections/",
        ResultViewSet.as_view({"get": "resolutions"}),
        name="tournament-corrections",
    ),
    path(
        "<uuid:tournament_pk>/corrections/<uuid:pk>/resolve/",
        ResultViewSet.as_view({"post": "resolve"}),
        name="tournament-correction-resolve",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/lineup/",
        action(DrawViewSet, "lineup"),
        name="tournament-event-match-lineup",
    ),
    path(
        "<uuid:tournament_pk>/events/<uuid:event_pk>/matches/<uuid:pk>/lineup/reset/",
        action(DrawViewSet, "lineup_reset"),
        name="tournament-event-match-lineup-reset",
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
            "self-check-in",
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
