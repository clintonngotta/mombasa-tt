from django.urls import path

from . import views

# Mounted under /organizations/<organization_pk>/.
organization_urlpatterns = [
    path("absence-rules/", views.AbsenceRulesView.as_view(), name="organization-absence-rules"),
    path("absence-penalties/", views.AbsencePenaltiesView.as_view(), name="organization-absence-penalties"),
    path(
        "absence-penalties/propose/",
        views.ProposeView.as_view(),
        name="organization-absence-penalties-propose",
    ),
    path(
        "absence-penalties/<uuid:pk>/issue/",
        views.IssueView.as_view(),
        name="organization-absence-penalty-issue",
    ),
    path(
        "absence-penalties/<uuid:pk>/waive/",
        views.WaiveView.as_view(),
        name="organization-absence-penalty-waive",
    ),
    path(
        "absence-penalties/<uuid:pk>/appeal/",
        views.AppealDecisionView.as_view(),
        name="organization-absence-penalty-appeal",
    ),
]

me_urlpatterns = [
    path("absence-penalties/", views.MyAbsencePenaltiesView.as_view(), name="my-absence-penalties"),
    path(
        "absence-penalties/<uuid:pk>/appeal/", views.MyAppealView.as_view(), name="my-absence-penalty-appeal"
    ),
]
