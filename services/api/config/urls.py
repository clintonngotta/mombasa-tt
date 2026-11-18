from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from competitions.urls import me_urlpatterns as my_entries
from competitions.urls import organization_urlpatterns as organization_tournaments
from core import views as core_views
from profiles.views import PlayerDetailView, PlayerDirectoryView
from ratings.views import PlayerRatingsView, RankingView
from scoring.urls import me_urlpatterns as my_scorecards
from scoring.urls import tournament_urlpatterns as umpires

api_v1 = [
    path("auth/", include("accounts.urls")),
    path("attachments/", include("attachments.urls")),
    path("me/", include("matchlog.urls")),
    path("me/", include("profiles.urls")),
    path("me/", include("organizations.me_urls")),
    path("me/", include(my_entries)),
    path("me/", include(my_scorecards)),
    path("scorecards/", include("scoring.urls")),
    path("organizations/", include("organizations.urls")),
    path("organizations/<uuid:organization_pk>/", include("facilities.urls")),
    path("organizations/<uuid:organization_pk>/", include(organization_tournaments)),
    path("tournaments/", include("competitions.urls")),
    path("tournaments/", include(umpires)),
    path("tournaments/", include("reservations.urls")),
    path("players/", PlayerDirectoryView.as_view(), name="player-directory"),
    path("players/<uuid:pk>/", PlayerDetailView.as_view(), name="player-detail"),
    path("players/<uuid:pk>/ratings/", PlayerRatingsView.as_view(), name="player-ratings"),
    path("rankings/", RankingView.as_view(), name="rankings"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
]

urlpatterns = [
    path("health/live", core_views.live, name="health-live"),
    path("health/ready", core_views.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("admin/", admin.site.urls),
]
