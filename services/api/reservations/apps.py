from django.apps import AppConfig


class ReservationsConfig(AppConfig):
    name = "reservations"
    verbose_name = "Tables and players in use"

    def ready(self):
        from competitions.signals import match_decided, rubber_decided

        from . import service

        # A result releases what the match held, in the transaction that records it (REQ-015).
        match_decided.connect(service.on_match_decided, dispatch_uid="reservations.match_decided")
        rubber_decided.connect(service.on_rubber_decided, dispatch_uid="reservations.rubber_decided")
