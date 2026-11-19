from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("drills", views.MyDrillViewSet, basename="my-drill")
router.register("training-plans", views.TrainingPlanViewSet, basename="training-plan")

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
library_urls = library.urls

club_plans = views.ClubTrainingPlanViewSet
club_items = views.ClubPlanItemViewSet
club_drills = [
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
