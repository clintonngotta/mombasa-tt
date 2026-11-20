from django.urls import path
from rest_framework.routers import SimpleRouter

from .booking_views import ClubBookingViewSet, MyBookingViewSet
from .door_views import MyVisitViewSet, PassViewSet, TakingsViewSet, VisitViewSet
from .views import FacilityViewSet, TrainingHoursView, VenueViewSet

finder = SimpleRouter()
finder.register("facilities", FacilityViewSet, basename="facility")
finder_urls = finder.urls

mine = SimpleRouter()
mine.register("facility-visits", MyVisitViewSet, basename="my-facility-visit")
mine.register("table-bookings", MyBookingViewSet, basename="my-table-booking")
my_urls = mine.urls

# Mounted under /organizations/<organization_pk>/.
urlpatterns = [
    path("training-hours/", TrainingHoursView.as_view(), name="organization-training-hours"),
    path("venues/", VenueViewSet.as_view({"get": "list", "post": "create"}), name="organization-venues"),
    path("venues/<uuid:pk>/", VenueViewSet.as_view({"patch": "partial_update"}), name="organization-venue"),
    path("bookings/", ClubBookingViewSet.as_view({"get": "list"}), name="organization-bookings"),
    path(
        "bookings/<uuid:pk>/approve/",
        ClubBookingViewSet.as_view({"post": "approve"}),
        name="organization-booking-approve",
    ),
    path(
        "bookings/<uuid:pk>/reject/",
        ClubBookingViewSet.as_view({"post": "reject"}),
        name="organization-booking-reject",
    ),
    path(
        "bookings/<uuid:pk>/cancel/",
        ClubBookingViewSet.as_view({"post": "cancel"}),
        name="organization-booking-cancel",
    ),
    path("facility-takings/", TakingsViewSet.as_view({"get": "list"}), name="organization-facility-takings"),
    path(
        "venues/<uuid:venue_pk>/passes/",
        PassViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-venue-passes",
    ),
    path(
        "venues/<uuid:venue_pk>/passes/<uuid:pk>/",
        PassViewSet.as_view({"patch": "partial_update"}),
        name="organization-venue-pass",
    ),
    path(
        "venues/<uuid:venue_pk>/visits/",
        VisitViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-venue-visits",
    ),
    path(
        "venues/<uuid:venue_pk>/visits/active-pass/",
        VisitViewSet.as_view({"get": "active_pass"}),
        name="organization-venue-visit-active-pass",
    ),
    path(
        "venues/<uuid:venue_pk>/visits/<uuid:pk>/reverse/",
        VisitViewSet.as_view({"post": "reverse"}),
        name="organization-venue-visit-reverse",
    ),
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
