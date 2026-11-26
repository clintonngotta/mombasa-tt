from django.urls import path
from rest_framework.routers import SimpleRouter

from . import committee, handover, images, profile, representatives, views

router = SimpleRouter()
router.register("", views.OrganizationViewSet, basename="organization")

join_request_views = views.JoinRequestViewSet
urlpatterns = [
    path("<uuid:pk>/profile/", profile.ClubProfileView.as_view(), name="organization-profile"),
    path(
        "<uuid:organization_pk>/images/", images.OrganizationImagesView.as_view(), name="organization-images"
    ),
    path(
        "<uuid:organization_pk>/images/<uuid:image_pk>/",
        images.OrganizationImageView.as_view(),
        name="organization-image",
    ),
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
        views.MemberViewSet.as_view({"get": "list", "post": "add"}),
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
    path(
        "<uuid:organization_pk>/members/<uuid:pk>/fields/",
        views.MemberFieldViewSet.as_view({"get": "member_values", "patch": "set_member_values"}),
        name="organization-member-fields",
    ),
    path(
        "<uuid:organization_pk>/member-fields/",
        views.MemberFieldViewSet.as_view({"get": "list", "post": "create"}),
        name="organization-member-field-list",
    ),
    path(
        "<uuid:organization_pk>/member-fields/<uuid:pk>/",
        views.MemberFieldViewSet.as_view({"patch": "partial_update"}),
        name="organization-member-field",
    ),
    path(
        "<uuid:organization_pk>/member-fields/<uuid:pk>/retire/",
        views.MemberFieldViewSet.as_view({"post": "retire"}),
        name="organization-member-field-retire",
    ),
    path(
        "<uuid:organization_pk>/member-fields/<uuid:pk>/restore/",
        views.MemberFieldViewSet.as_view({"post": "restore"}),
        name="organization-member-field-restore",
    ),
    path(
        "<uuid:organization_pk>/admin/",
        handover.OrganizationAdminView.as_view(),
        name="organization-admin",
    ),
    path(
        "<uuid:organization_pk>/admin/nominate/",
        handover.NominateAdminView.as_view(),
        name="organization-admin-nominate",
    ),
    path(
        "<uuid:organization_pk>/admin/cancel/",
        handover.CancelNominationView.as_view(),
        name="organization-admin-cancel",
    ),
    path(
        "<uuid:organization_pk>/admin/step-down/",
        handover.StepDownAdminView.as_view(),
        name="organization-admin-step-down",
    ),
    path(
        "<uuid:organization_pk>/admin/appoint/",
        handover.AppointAdminView.as_view(),
        name="organization-admin-appoint",
    ),
    path(
        "<uuid:organization_pk>/committee/",
        committee.CommitteeView.as_view(),
        name="organization-committee",
    ),
    path(
        "<uuid:organization_pk>/committee/history/",
        committee.CommitteeHistoryView.as_view(),
        name="organization-committee-history",
    ),
    path(
        "<uuid:organization_pk>/committee/candidates/",
        committee.CommitteeCandidatesView.as_view(),
        name="organization-committee-candidates",
    ),
    path(
        "<uuid:organization_pk>/committee/positions/",
        committee.PositionsView.as_view(),
        name="organization-committee-positions",
    ),
    path(
        "<uuid:organization_pk>/committee/positions/reorder/",
        committee.ReorderPositionsView.as_view(),
        name="organization-committee-positions-reorder",
    ),
    path(
        "<uuid:organization_pk>/committee/positions/<uuid:pk>/",
        committee.PositionView.as_view(),
        name="organization-committee-position",
    ),
    path(
        "<uuid:organization_pk>/committee/positions/<uuid:pk>/retire/",
        committee.RetirePositionView.as_view(),
        name="organization-committee-position-retire",
    ),
    path(
        "<uuid:organization_pk>/committee/positions/<uuid:pk>/holder/",
        committee.PositionHolderView.as_view(),
        name="organization-committee-position-holder",
    ),
    path(
        "<uuid:organization_pk>/committee/positions/<uuid:pk>/values/",
        committee.PositionValuesView.as_view(),
        name="organization-committee-position-values",
    ),
    path(
        "<uuid:organization_pk>/committee/fields/",
        committee.CommitteeFieldsView.as_view(),
        name="organization-committee-fields",
    ),
    path(
        "<uuid:organization_pk>/committee/fields/<uuid:pk>/",
        committee.CommitteeFieldView.as_view(),
        name="organization-committee-field",
    ),
    path(
        "<uuid:organization_pk>/committee/fields/<uuid:pk>/retire/",
        committee.CommitteeFieldRetireView.as_view(),
        name="organization-committee-field-retire",
    ),
    path(
        "<uuid:organization_pk>/committee/fields/<uuid:pk>/restore/",
        committee.CommitteeFieldRestoreView.as_view(),
        name="organization-committee-field-restore",
    ),
    path(
        "<uuid:organization_pk>/representatives/",
        representatives.RepresentativesView.as_view(),
        name="organization-representatives",
    ),
    path(
        "<uuid:organization_pk>/representatives/cap/",
        representatives.CapView.as_view(),
        name="organization-representatives-cap",
    ),
    path(
        "<uuid:organization_pk>/representatives/<uuid:pk>/withdraw/",
        representatives.WithdrawView.as_view(),
        name="organization-representative-withdraw",
    ),
    path(
        "<uuid:organization_pk>/representatives/<uuid:pk>/accept/",
        representatives.AcceptView.as_view(),
        name="organization-representative-accept",
    ),
    path(
        "<uuid:organization_pk>/representatives/<uuid:pk>/decline/",
        representatives.DeclineView.as_view(),
        name="organization-representative-decline",
    ),
    path(
        "<uuid:organization_pk>/representatives/<uuid:pk>/remove/",
        representatives.RemoveView.as_view(),
        name="organization-representative-remove",
    ),
    *router.urls,
]
