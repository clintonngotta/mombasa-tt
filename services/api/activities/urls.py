from django.urls import path

from .views import ActivityViewSet, ScheduleCalendarView, ScheduleView

activities = ActivityViewSet
# Mounted under /organizations/<organization_pk>/.
urlpatterns = [
    path(
        "activities/", activities.as_view({"get": "list", "post": "create"}), name="organization-activities"
    ),
    path(
        "activities/<uuid:pk>/",
        activities.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="organization-activity",
    ),
    path(
        "activities/<uuid:pk>/publish/",
        activities.as_view({"post": "publish"}),
        name="organization-activity-publish",
    ),
    path(
        "activities/<uuid:pk>/cancel/",
        activities.as_view({"post": "cancel"}),
        name="organization-activity-cancel",
    ),
    path(
        "activities/<uuid:pk>/rsvp/", activities.as_view({"post": "rsvp"}), name="organization-activity-rsvp"
    ),
    path(
        "activities/<uuid:pk>/attendees/",
        activities.as_view({"get": "attendees"}),
        name="organization-activity-attendees",
    ),
    path(
        "activities/<uuid:pk>/invitees/",
        activities.as_view({"get": "invitee_list"}),
        name="organization-activity-invitees",
    ),
    path("schedule/", ScheduleView.as_view(), name="organization-schedule"),
    path("schedule.ics", ScheduleCalendarView.as_view(), name="organization-schedule-ics"),
]
