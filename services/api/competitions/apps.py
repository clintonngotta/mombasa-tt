from django.apps import AppConfig


class CompetitionsConfig(AppConfig):
    name = "competitions"
    verbose_name = "Tournaments and events"

    def ready(self):
        # The outbox worker finds its handlers by their being registered: that happens on import.
        from . import official, publication  # noqa: F401
