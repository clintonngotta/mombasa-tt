from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("", views.OrganizationViewSet, basename="organization")

join_request_views = views.JoinRequestViewSet
urlpatterns = [
    path(
        "<uuid:organization_pk>/join-requests/",
        join_request_views.as_view({"get": "list", "post": "create"}),
        name="organization-join-requests",
    ),
    path(
        "<uuid:organization_pk>/join-requests/<uuid:pk>/approve/",
        join_request_views.as_view({"post": "approve"}),
        name="organization-join-request-approve",
    ),
    path(
        "<uuid:organization_pk>/join-requests/<uuid:pk>/reject/",
        join_request_views.as_view({"post": "reject"}),
        name="organization-join-request-reject",
    ),
    path(
        "<uuid:organization_pk>/invitations/",
        views.InvitationViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-invitations",
    ),
    path(
        "<uuid:organization_pk>/invitations/<uuid:pk>/revoke/",
        views.InvitationViewSet.as_view({"post": "revoke"}),
        name="organization-invitation-revoke",
    ),
    path("permissions/", views.PermissionCatalogView.as_view(), name="organization-permissions"),
    path(
        "<uuid:organization_pk>/roles/",
        views.RoleViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-roles",
    ),
    path(
        "<uuid:organization_pk>/roles/<uuid:pk>/",
        views.RoleViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="organization-role",
    ),
    path(
        "<uuid:organization_pk>/members/",
        views.MemberViewSet.as_view({"get": "list"}),
        name="organization-members",
    ),
    path(
        "<uuid:organization_pk>/members/<uuid:pk>/roles/",
        views.MemberViewSet.as_view({"put": "set_roles"}),
        name="organization-member-roles",
    ),
    path(
        "<uuid:organization_pk>/members/<uuid:pk>/remove/",
        views.MemberViewSet.as_view({"post": "remove"}),
        name="organization-member-remove",
    ),
    *router.urls,
]
