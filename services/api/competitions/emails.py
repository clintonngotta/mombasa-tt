from django.conf import settings
from django.core.mail import send_mail

from .models import Entry

NEWS = {
    "entered": ("You've been entered in {event}", "{actor} entered you in {event} at {tournament}."),
    "accepted": ("Your entry in {event} is accepted", "Your entry in {event} at {tournament} is accepted."),
    "promoted": (
        "A place opened up in {event}",
        "A place opened up: your entry in {event} at {tournament} has moved from the waiting list and is "
        "now accepted.",
    ),
    "waitlisted": (
        "You're on the waiting list for {event}",
        "{event} at {tournament} is full for now, so your entry is on the waiting list. The organizers "
        "will tell you if a place opens up.",
    ),
    "rejected": (
        "Your entry in {event} was not accepted",
        "Your entry in {event} at {tournament} was not accepted.",
    ),
    "withdrawn": (
        "Your entry in {event} was withdrawn",
        "{actor} withdrew your entry in {event} at {tournament}.",
    ),
}


def send_entry_news(entry: Entry, news: str, actor) -> None:
    """Tell the entry's players what happened to it, except the one who did it."""
    subject, line = NEWS[news]
    event = entry.event
    words = {"event": event.name, "tournament": event.tournament.name, "actor": actor.display_name}
    body = line.format(**words)
    if entry.reason and news in {"rejected", "withdrawn"}:
        body += f"\n\nReason given: {entry.reason}"
    if news in {"entered", "accepted", "promoted"} and event.entry_fee_minor:
        body += "\n\nThis says nothing about the entry fee: pay it the way the organizers ask."
    body += f"\n\nSee the tournament: {settings.FRONTEND_URL}/tournaments/{event.tournament_id}"
    # One message each, so players never see each other's addresses.
    for place in entry.players.all():
        if place.user_id != actor.id:
            send_mail(subject.format(**words), body, None, [place.user.email])
