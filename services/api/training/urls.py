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

club_drills = [
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
