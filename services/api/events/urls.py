from django.urls import path

from .views import (
    ClubExternalEventsView,
    ClubExternalEventView,
    CuratorActionView,
    EventListingView,
    MarkLiveView,
    ReportLinkView,
    ReviewQueueView,
)

urlpatterns = [
    path("events/", EventListingView.as_view(), name="events"),
    path("external-events/review/", ReviewQueueView.as_view(), name="external-event-review"),
    path(
        "external-events/<uuid:pk>/approve/",
        CuratorActionView.as_view(action="approve"),
        name="external-event-approve",
    ),
    path(
        "external-events/<uuid:pk>/reject/",
        CuratorActionView.as_view(action="reject"),
        name="external-event-reject",
    ),
    path(
        "external-events/<uuid:pk>/remove-link/",
        CuratorActionView.as_view(action="remove_link"),
        name="external-event-remove-link",
    ),
    path("external-events/<uuid:pk>/report/", ReportLinkView.as_view(), name="external-event-report"),
]

# Mounted under /organizations/<organization_pk>/.
club_urls = [
    path("external-events/", ClubExternalEventsView.as_view(), name="organization-external-events"),
    path("external-events/<uuid:pk>/", ClubExternalEventView.as_view(), name="organization-external-event"),
    path("external-events/<uuid:pk>/live/", MarkLiveView.as_view(), name="organization-external-event-live"),
]
