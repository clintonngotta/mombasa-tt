from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AnnouncementView, InboxViewSet, PreferencesView

router = SimpleRouter()
router.register("notifications", InboxViewSet, basename="notification")
# Mounted under /me/.
my_urls = [
    path("notification-preferences/", PreferencesView.as_view(), name="my-notification-preferences"),
    *router.urls,
]
# Mounted under /organizations/<organization_pk>/.
club_urls = [path("announcements/", AnnouncementView.as_view(), name="organization-announcements")]
