from django.urls import path
from rest_framework.routers import SimpleRouter

from . import handover, views

router = SimpleRouter()
router.register("invitations", views.MyInvitationViewSet, basename="me-invitation")
router.register("admin-nominations", handover.MyAdminNominationViewSet, basename="me-admin-nomination")
router.register("memberships", views.MyMembershipViewSet, basename="me-membership")

urlpatterns = [
    path(
        "managed-organizations/", views.MyManagedOrganizationsView.as_view(), name="me-managed-organizations"
    ),
    path("join-requests/", views.MyJoinRequestsView.as_view(), name="me-join-requests"),
    *router.urls,
]
