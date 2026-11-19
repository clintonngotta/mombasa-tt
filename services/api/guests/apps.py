from django.apps import AppConfig


class GuestsConfig(AppConfig):
    name = "guests"
    verbose_name = "Guests"

    def ready(self):
        # Registers the outbox handler that re-rates players after a guest is claimed.
        from . import merge  # noqa: F401
