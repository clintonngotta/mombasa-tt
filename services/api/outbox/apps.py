from django.apps import AppConfig


class OutboxConfig(AppConfig):
    name = "outbox"
    verbose_name = "Work to do after a change is saved"
