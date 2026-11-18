from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        from . import schema  # noqa: F401  registers OpenAPI extensions
        from django.apps import apps
        from django.contrib import admin

        from .admin import PlatformOnlyAdmin

        for app in ("competitions", "facilities", "organizations", "profiles", "ratings", "reservations", "scoring"):
            for model in apps.get_app_config(app).get_models():
                if not admin.site.is_registered(model):
                    admin.site.register(model, PlatformOnlyAdmin)
