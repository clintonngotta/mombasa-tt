from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ChallengeViewSet, ClubChallengesView, MySodaSettingsView, SodaPolicyView

router = SimpleRouter()
router.register("soda-games", ChallengeViewSet, basename="soda-game")
# Mounted under /me/.
my_urls = [path("soda-settings/", MySodaSettingsView.as_view(), name="my-soda-settings"), *router.urls]
# Mounted under /organizations/<organization_pk>/.
club_urls = [
    path("soda-games/", ClubChallengesView.as_view(), name="organization-soda-games"),
    path("soda-policy/", SodaPolicyView.as_view(), name="organization-soda-policy"),
]
