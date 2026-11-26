from django.urls import path

from . import views

# Mounted under /organizations/<organization_pk>/.
organization_urlpatterns = [
    path("feedback-forms/", views.FeedbackFormsView.as_view(), name="organization-feedback-forms"),
    path("feedback-forms/<uuid:pk>/", views.FeedbackFormView.as_view(), name="organization-feedback-form"),
    path(
        "feedback-forms/<uuid:pk>/send/",
        views.SendFormView.as_view(),
        name="organization-feedback-form-send",
    ),
    path(
        "feedback-forms/<uuid:pk>/closing/",
        views.ClosingView.as_view(),
        name="organization-feedback-form-closing",
    ),
    path(
        "feedback-forms/<uuid:pk>/totals/",
        views.TotalsView.as_view(),
        name="organization-feedback-form-totals",
    ),
    path(
        "feedback-forms/<uuid:pk>/export.csv",
        views.ExportView.as_view(),
        name="organization-feedback-form-export",
    ),
]

me_urlpatterns = [path("feedback-forms/", views.MyFeedbackFormsView.as_view(), name="my-feedback-forms")]

urlpatterns = [path("feedback-forms/<uuid:pk>/", views.MyFeedbackFormView.as_view(), name="feedback-form")]
