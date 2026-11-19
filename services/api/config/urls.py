from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from coaching.urls import coach_urlpatterns
from coaching.urls import me_urlpatterns as my_coaching
from competitions.urls import me_urlpatterns as my_entries
from competitions.urls import organization_urlpatterns as organization_tournaments
from core import views as core_views
from core.catalogue import CountryCatalogueView, CountryOptionsView
from facilities.urls import finder_urls
from facilities.urls import my_urls as facility_my_urls
from guests.urls import club_urlpatterns as club_guests
from guests.urls import me_urlpatterns as my_guest_claims
from profiles.views import PlayerDetailView, PlayerDirectoryView
from ratings.views import ClubRankingView, GeographyRankingView, PlayerRatingsView, RankingView
from regions.urls import body_urlpatterns as regional_bodies
from regions.urls import me_urlpatterns as my_region
from regions.urls import organization_urlpatterns as body_routes
from regions.urls import tournament_urlpatterns as sponsorships
from scoring.urls import me_urlpatterns as my_scorecards
from scoring.urls import tournament_urlpatterns as umpires
from soda.urls import club_urls as soda_club_urls
from soda.urls import my_urls as soda_my_urls
from training.urls import club_drills, library_urls

api_v1 = [
    path("auth/", include("accounts.urls")),
    path("attachments/", include("attachments.urls")),
    path("me/", include("matchlog.urls")),
    path("me/", include("profiles.urls")),
    path("me/", include("organizations.me_urls")),
    path("me/", include(my_entries)),
    path("me/", include(my_scorecards)),
    path("me/", include("training.urls")),
    path("me/", include(facility_my_urls)),
    path("me/", include(soda_my_urls)),
    path("me/", include(my_region)),
    path("me/", include(my_coaching)),
    path("me/", include(my_guest_claims)),
    path("coaches/", include(coach_urlpatterns)),
    path("scorecards/", include("scoring.urls")),
    path("organizations/", include("organizations.urls")),
    path("organizations/<uuid:organization_pk>/", include("facilities.urls")),
    path("organizations/<uuid:organization_pk>/", include("activities.urls")),
    path("organizations/<uuid:organization_pk>/", include(soda_club_urls)),
    path("organizations/<uuid:organization_pk>/", include(organization_tournaments)),
    path("organizations/<uuid:organization_pk>/", include(club_drills)),
    path("organizations/<uuid:organization_pk>/", include(club_guests)),
    path("organizations/<uuid:organization_pk>/", include(body_routes)),
    path("regional-bodies/", include(regional_bodies)),
    path("tournaments/", include("competitions.urls")),
    path("tournaments/", include(umpires)),
    path("tournaments/", include("reservations.urls")),
    path("tournaments/", include(sponsorships)),
    path("", include(library_urls)),
    path("", include(finder_urls)),
    path("players/", PlayerDirectoryView.as_view(), name="player-directory"),
    path("players/<uuid:pk>/", PlayerDetailView.as_view(), name="player-detail"),
    path("players/<uuid:pk>/ratings/", PlayerRatingsView.as_view(), name="player-ratings"),
    path("rankings/", RankingView.as_view(), name="rankings"),
    path("rankings/clubs/", ClubRankingView.as_view(), name="club-rankings"),
    path("rankings/geography/", GeographyRankingView.as_view(), name="geography-rankings"),
    path("geography/countries/", CountryOptionsView.as_view(), name="geography-countries"),
    path("geography/countries/<str:code>/", CountryCatalogueView.as_view(), name="geography-country"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
]

urlpatterns = [
    path("health/live", core_views.live, name="health-live"),
    path("health/ready", core_views.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("admin/", admin.site.urls),
]
