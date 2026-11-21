"""Tell open pages that something they show has changed (TASK-007).

A message says only what changed (a tournament's scores or results) and never carries the data
itself: the page fetches it again through the API, which applies the viewer's permissions. Messages go
after the transaction commits, so nobody is told about a change that was rolled back. They are best
effort: a page that misses one still refreshes on its own timer.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)

# "board": the match-day board of tables and calls (TASK-082) changed.
TOPICS = {"scores", "results", "board"}


def tournament_group(tournament_id) -> str:
    return f"tournament.{tournament_id}"


def tournament_changed(tournament_id, topic: str, *, event_id=None) -> None:
    """After commit, tell the tournament's open pages that its `topic` changed, in `event_id` if given."""
    if topic not in TOPICS:
        raise ValueError(f"Unknown topic {topic!r}")
    message = {"type": "changed", "topic": topic, "event": str(event_id) if event_id else None}
    group = tournament_group(tournament_id)
    transaction.on_commit(lambda: _send(group, message))


def _send(group: str, message: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group, message)
    except Exception:  # Redis down: pages fall back to polling, the change itself is saved.
        logger.warning("Could not broadcast %s to %s", message["topic"], group, exc_info=True)
