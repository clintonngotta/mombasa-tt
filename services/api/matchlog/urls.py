from rest_framework.routers import SimpleRouter

from .views import PersonalMatchViewSet

router = SimpleRouter()
router.register("matches", PersonalMatchViewSet, basename="personal-match")
urlpatterns = router.urls
