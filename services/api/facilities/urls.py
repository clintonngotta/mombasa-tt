from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import FacilityViewSet, TrainingHoursView, VenueViewSet

finder = SimpleRouter()
finder.register("facilities", FacilityViewSet, basename="facility")
finder_urls = finder.urls

# Mounted under /organizations/<organization_pk>/.
urlpatterns = [
    path("training-hours/", TrainingHoursView.as_view(), name="organization-training-hours"),
    path("venues/", VenueViewSet.as_view({"get": "list", "post": "create"}), name="organization-venues"),
    path("venues/<uuid:pk>/", VenueViewSet.as_view({"patch": "partial_update"}), name="organization-venue"),
    path("venues/<uuid:pk>/hours/", VenueViewSet.as_view({"put": "hours"}), name="organization-venue-hours"),
    path(
        "venues/<uuid:pk>/tables/",
        VenueViewSet.as_view({"post": "add_table"}),
        name="organization-venue-tables",
    ),
    path(
        "venues/<uuid:pk>/tables/<uuid:table_pk>/",
        VenueViewSet.as_view({"patch": "update_table"}),
        name="organization-venue-table",
    ),
]
