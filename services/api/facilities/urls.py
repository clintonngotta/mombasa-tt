from django.urls import path

from .views import VenueViewSet

# Mounted under /organizations/<organization_pk>/.
urlpatterns = [
    path("venues/", VenueViewSet.as_view({"get": "list", "post": "create"}), name="organization-venues"),
    path("venues/<uuid:pk>/", VenueViewSet.as_view({"patch": "partial_update"}), name="organization-venue"),
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
