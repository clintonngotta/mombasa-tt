from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    name = "organizations"
    verbose_name = "Organizations"

    def ready(self):
        # Registers the outbox handler for nomination emails.
        from . import handover  # noqa: F401
