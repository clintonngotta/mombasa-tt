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
