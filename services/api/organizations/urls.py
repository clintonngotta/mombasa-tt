from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("", views.OrganizationViewSet, basename="organization")

join_requests = views.JoinRequestViewSet
urlpatterns = [
    path(
        "<uuid:organization_pk>/join-requests/",
        join_requests.as_view({"get": "list", "post": "create"}),
        name="organization-join-requests",
    ),
    path(
        "<uuid:organization_pk>/join-requests/<uuid:pk>/approve/",
        join_requests.as_view({"post": "approve"}),
        name="organization-join-request-approve",
    ),
    path(
        "<uuid:organization_pk>/join-requests/<uuid:pk>/reject/",
        join_requests.as_view({"post": "reject"}),
        name="organization-join-request-reject",
    ),
    *router.urls,
]
