from django.urls import path

from . import views

urlpatterns = [
    path("profile/", views.ProfileView.as_view(), name="me-profile"),
    path("avatar/", views.AvatarView.as_view(), name="me-avatar"),
    path("goals/", views.GoalsView.as_view(), name="me-goals"),
    path("onboarding/complete/", views.CompleteOnboardingView.as_view(), name="me-onboarding-complete"),
]
