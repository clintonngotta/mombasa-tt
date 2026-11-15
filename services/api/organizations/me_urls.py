from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("invitations", views.MyInvitationViewSet, basename="me-invitation")

urlpatterns = [
    path("memberships/", views.MyMembershipsView.as_view(), name="me-memberships"),
    path("join-requests/", views.MyJoinRequestsView.as_view(), name="me-join-requests"),
    *router.urls,
]
