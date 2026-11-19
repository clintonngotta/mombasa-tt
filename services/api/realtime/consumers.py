from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from competitions.models import Tournament
from organizations.access import effective_permissions
from organizations.permissions import Permission

from .broadcast import tournament_group

NOT_SIGNED_IN = 4401
NOT_FOUND = 4404


@database_sync_to_async
def can_watch(user, tournament_id) -> bool:
    """Who may see the tournament: everyone signed in once it is published, its host's competition staff
    while it is a draft."""
    tournament = Tournament.objects.select_related("organization").filter(pk=tournament_id).first()
    if tournament is None:
        return False
    if tournament.status != Tournament.Status.DRAFT:
        return True
    return Permission.COMPETITIONS_MANAGE in effective_permissions(user, tournament.organization)


class TournamentConsumer(AsyncJsonWebsocketConsumer):
    """/api/v1/ws/tournaments/{id}/: pushes {"type": "changed", "topic", "event"} when the tournament's
    scores or results change. The browser only listens; anything it sends is ignored."""

    group = None

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=NOT_SIGNED_IN)
            return
        tournament_id = self.scope["url_route"]["kwargs"]["tournament_id"]
        if not await can_watch(user, tournament_id):
            await self.close(code=NOT_FOUND)
            return
        self.group = tournament_group(tournament_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        return

    async def changed(self, message):
        await self.send_json({"type": "changed", "topic": message["topic"], "event": message["event"]})
