from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

club = SimpleRouter()
club.register("guests", views.GuestViewSet, basename="organization-guest")
club.register("guest-claims", views.GuestClaimViewSet, basename="organization-guest-claim")

me = SimpleRouter()
me.register("guest-invitations", views.MyGuestInvitationViewSet, basename="me-guest-invitation")
me.register("guest-claims", views.MyGuestClaimViewSet, basename="me-guest-claim")

club_urlpatterns = club.urls
me_urlpatterns = me.urls

# Invitation links: /auth/invitations/<token>/ (public), .../claim/ (signed in).
link_urlpatterns = [
    path("invitations/<str:token>/", views.JoinInvitationView.as_view(), name="auth-invitation"),
    path("invitations/<str:token>/claim/", views.ClaimByLinkView.as_view(), name="auth-invitation-claim"),
]
