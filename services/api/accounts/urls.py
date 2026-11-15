from django.urls import path

from . import views

urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("signup/", views.SignUpView.as_view(), name="auth-signup"),
    path("verification/resend/", views.ResendVerificationView.as_view(), name="auth-verification-resend"),
    path("verification/confirm/", views.VerifyEmailView.as_view(), name="auth-verification-confirm"),
    path("login/", views.LogInView.as_view(), name="auth-login"),
    path("logout/", views.LogOutView.as_view(), name="auth-logout"),
    path("password-reset/", views.PasswordResetView.as_view(), name="auth-password-reset"),
    path(
        "password-reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("me/", views.MeView.as_view(), name="auth-me"),
]
