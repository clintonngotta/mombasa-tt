from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from core import views as core_views
from profiles.views import PlayerDetailView, PlayerDirectoryView

api_v1 = [
    path("auth/", include("accounts.urls")),
    path("me/", include("matchlog.urls")),
    path("me/", include("profiles.urls")),
    path("me/", include("organizations.me_urls")),
    path("organizations/", include("organizations.urls")),
    path("players/", PlayerDirectoryView.as_view(), name="player-directory"),
    path("players/<uuid:pk>/", PlayerDetailView.as_view(), name="player-detail"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
]

urlpatterns = [
    path("health/live", core_views.live, name="health-live"),
    path("health/ready", core_views.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("admin/", admin.site.urls),
]
