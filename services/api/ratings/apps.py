from django.apps import AppConfig


class RatingsConfig(AppConfig):
    name = "ratings"
    verbose_name = "Ratings"

    def ready(self):
        from competitions import official

        from . import service

        # Ratings follow from official results: the outbox worker calls this for every result that
        # starts to stand, is replaced or is struck out (REQ-015, REQ-016).
        if service.project not in official.PROJECTIONS:
            official.PROJECTIONS.append(service.project)
