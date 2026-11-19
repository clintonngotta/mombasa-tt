from rest_framework.routers import SimpleRouter

from .views import MatchNoteViewSet, PersonalMatchViewSet

router = SimpleRouter()
router.register("matches", PersonalMatchViewSet, basename="personal-match")
router.register("match-notes", MatchNoteViewSet, basename="match-note")
urlpatterns = router.urls
