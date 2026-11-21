from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AnnouncementView,
    InboxViewSet,
    PreferencesView,
    PushDeviceView,
    PushSubscribeView,
    PushUnsubscribeView,
    PushView,
)

router = SimpleRouter()
router.register("notifications", InboxViewSet, basename="notification")
# Mounted under /me/.
my_urls = [
    path("notification-preferences/", PreferencesView.as_view(), name="my-notification-preferences"),
    path("push/", PushView.as_view(), name="my-push"),
    path("push/subscribe/", PushSubscribeView.as_view(), name="my-push-subscribe"),
    path("push/unsubscribe/", PushUnsubscribeView.as_view(), name="my-push-unsubscribe"),
    path("push/devices/<uuid:device_pk>/", PushDeviceView.as_view(), name="my-push-device"),
    *router.urls,
]
# Mounted under /organizations/<organization_pk>/.
club_urls = [path("announcements/", AnnouncementView.as_view(), name="organization-announcements")]
