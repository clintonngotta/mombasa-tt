from django.urls import path
from rest_framework.routers import SimpleRouter

from . import club_session_views as session_views
from . import views

router = SimpleRouter()
router.register("drills", views.MyDrillViewSet, basename="my-drill")
router.register("training-plans", views.TrainingPlanViewSet, basename="training-plan")
router.register(
    "session-invitations", session_views.MySessionInvitationViewSet, basename="my-session-invitation"
)

items = views.PlanItemViewSet
urlpatterns = [
    path("equipment/", views.EquipmentView.as_view(), name="my-equipment"),
    path("training-sessions/", views.UpcomingSessionsView.as_view(), name="my-training-sessions"),
    path(
        "training-plans/<uuid:plan_pk>/items/", items.as_view({"post": "create"}), name="training-plan-items"
    ),
    path(
        "training-plans/<uuid:plan_pk>/items/<uuid:pk>/",
        items.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="training-plan-item",
    ),
    *router.urls,
]

library = SimpleRouter()
library.register("drills", views.DrillLibraryViewSet, basename="drill-library")
library.register("open-sessions", session_views.OpenSessionViewSet, basename="open-session")
library_urls = library.urls

club_plans = views.ClubTrainingPlanViewSet
club_items = views.ClubPlanItemViewSet
club_sessions = session_views.ClubSessionViewSet
session_invitations = session_views.SessionInvitationViewSet
club_drills = [
    path(
        "club-sessions/",
        club_sessions.as_view({"get": "list", "post": "create"}),
        name="organization-club-sessions",
    ),
    path(
        "club-sessions/<uuid:pk>/",
        club_sessions.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="organization-club-session",
    ),
    path(
        "club-sessions/<uuid:pk>/cancel/",
        club_sessions.as_view({"post": "cancel"}),
        name="organization-club-session-cancel",
    ),
    path(
        "club-sessions/<uuid:session_pk>/invitations/",
        session_invitations.as_view({"get": "list", "post": "create"}),
        name="organization-club-session-invitations",
    ),
    path(
        "club-sessions/<uuid:session_pk>/invitations/<uuid:pk>/",
        session_invitations.as_view({"patch": "partial_update"}),
        name="organization-club-session-invitation",
    ),
    path(
        "training-plans/",
        club_plans.as_view({"get": "list", "post": "create"}),
        name="organization-training-plans",
    ),
    path(
        "training-plans/<uuid:pk>/",
        club_plans.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="organization-training-plan",
    ),
    path(
        "training-plans/<uuid:pk>/recommendations/",
        club_plans.as_view({"get": "recommendations"}),
        name="organization-training-plan-recommendations",
    ),
    path(
        "training-plans/<uuid:plan_pk>/items/",
        club_items.as_view({"post": "create"}),
        name="organization-training-plan-items",
    ),
    path(
        "training-plans/<uuid:plan_pk>/items/<uuid:pk>/",
        club_items.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="organization-training-plan-item",
    ),
    path(
        "drills/",
        views.ClubDrillViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-drills",
    ),
    path(
        "drills/<uuid:pk>/",
        views.ClubDrillViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="organization-drill",
    ),
]
