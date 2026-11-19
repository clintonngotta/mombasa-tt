from django.urls import path

from .consumers import TournamentConsumer

websocket_urlpatterns = [
    path("api/v1/ws/tournaments/<uuid:tournament_id>/", TournamentConsumer.as_asgi()),
]
