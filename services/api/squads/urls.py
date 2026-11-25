from django.urls import path

from . import views
from .models import SquadPlace

# Mounted under /organizations/<organization_pk>/.
organization_urlpatterns = [
    path("squads/", views.SquadsView.as_view(), name="organization-squads"),
    path("squads/history/", views.HistoryView.as_view(), name="organization-squad-history"),
    path("squads/<uuid:pk>/", views.SquadView.as_view(), name="organization-squad"),
    path("squads/<uuid:pk>/publish/", views.PublishSquadView.as_view(), name="organization-squad-publish"),
    path(
        "squads/<uuid:pk>/recommendation/",
        views.RecommendationView.as_view(),
        name="organization-squad-recommendation",
    ),
    path("squads/<uuid:pk>/places/", views.PlacesView.as_view(), name="organization-squad-places"),
    path(
        "squads/<uuid:pk>/places/<uuid:place_pk>/remove/",
        views.RemovePlaceView.as_view(),
        name="organization-squad-place-remove",
    ),
]

me_urlpatterns = [
    path("squad-places/", views.MySquadPlacesView.as_view(), name="my-squad-places"),
    path(
        "squad-places/<uuid:pk>/accept/",
        views.AnswerPlaceView.as_view(answer=SquadPlace.Status.ACCEPTED),
        name="my-squad-place-accept",
    ),
    path(
        "squad-places/<uuid:pk>/decline/",
        views.AnswerPlaceView.as_view(answer=SquadPlace.Status.DECLINED),
        name="my-squad-place-decline",
    ),
]
