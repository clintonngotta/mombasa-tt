from django.urls import path

from . import views

items = views.TraineePlanItemViewSet

me_urlpatterns = [
    path("coach-profile/", views.MyCoachProfileView.as_view(), name="my-coach-profile"),
    path("coach-profile/organizer/", views.MyOrganizerView.as_view(), name="my-coach-organizer"),
    path("coach-availability/", views.MyAvailabilityView.as_view(), name="my-coach-availability"),
    path("coach-calendar/", views.CoachCalendarView.as_view(), name="my-coach-calendar"),
    path("coach-notes/", views.MyCoachNotesView.as_view(), name="my-coach-notes"),
    path("coach-comments/<uuid:pk>/", views.CoachCommentView.as_view(), name="my-coach-comment"),
    path("coachings/", views.MyCoachingsView.as_view(), name="my-coachings"),
    *[
        path(
            f"coachings/<uuid:pk>/{action}/",
            views.CoachingActionView.as_view(action=action),
            name=f"my-coaching-{action}",
        )
        for action in ("accept", "decline", "end")
    ],
    path("trainees/<uuid:pk>/", views.TraineeView.as_view(), name="my-trainee"),
    path("trainees/<uuid:pk>/plans/", views.TraineePlansView.as_view(), name="my-trainee-plans"),
    path("trainees/<uuid:pk>/plans/<uuid:plan_pk>/", views.TraineePlanView.as_view(), name="my-trainee-plan"),
    path(
        "trainees/<uuid:pk>/plans/<uuid:plan_pk>/recommendations/",
        views.TraineePlanRecommendationsView.as_view(),
        name="my-trainee-plan-recommendations",
    ),
    path(
        "trainees/<uuid:coaching_pk>/plans/<uuid:plan_pk>/items/",
        items.as_view({"post": "create"}),
        name="my-trainee-plan-items",
    ),
    path(
        "trainees/<uuid:coaching_pk>/plans/<uuid:plan_pk>/items/<uuid:pk>/",
        items.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="my-trainee-plan-item",
    ),
    path("trainees/<uuid:pk>/comments/", views.TraineeCommentsView.as_view(), name="my-trainee-comments"),
    path("bookings/", views.MyBookingsView.as_view(), name="my-bookings"),
    *[
        path(
            f"bookings/<uuid:pk>/{action}/",
            views.BookingActionView.as_view(action=action),
            name=f"my-booking-{action}",
        )
        for action in ("confirm", "decline", "cancel")
    ],
]

coach_urlpatterns = [
    path("", views.CoachListView.as_view(), name="coaches"),
    path("<uuid:pk>/", views.CoachDetailView.as_view(), name="coach"),
    path("<uuid:pk>/slots/", views.CoachSlotsView.as_view(), name="coach-slots"),
]
